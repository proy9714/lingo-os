"""Provider adapters. Each turns one request into one HTTP call and reports token counts."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from app.ai.config import ProviderConfig


@dataclass
class LLMRequest:
    system: str
    prompt: str
    model: str
    temperature: float | None = None
    schema: dict[str, Any] | None = None  # ask for JSON matching this JSON schema
    thinking: str | None = None
    timeout: float = 40.0
    history: list[tuple[str, str]] | None = None  # earlier turns as (role 'user'|'assistant', text); `prompt` is the newest


@dataclass
class LLMResponse:
    text: str
    tokens_in: int | None = None
    tokens_out: int | None = None


class ProviderError(Exception):
    def __init__(self, message: str, *, status: int | None = None, model_missing: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.model_missing = model_missing


def _error_text(response: httpx.Response) -> str:
    try:
        body = response.json()
        if isinstance(body, dict):
            err = body.get("error")
            if isinstance(err, dict):
                return str(err.get("message") or err)[:300]
            if err:
                return str(err)[:300]
    except ValueError:
        pass
    return response.text[:300] or response.reason_phrase


class _HTTPProvider:
    """Creates its HTTP client on first use: loading TLS certificates is slow and most app starts never call a model."""

    base_url = ""

    def __init__(self, cfg: ProviderConfig, transport: httpx.BaseTransport | None = None) -> None:
        self.cfg = cfg
        self._transport = transport
        self._client: httpx.Client | None = None

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(base_url=self.base_url, transport=self._transport)
        return self._client


class GeminiProvider(_HTTPProvider):
    """Google Gemini through the public REST API (generateContent)."""

    BASE = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(self, cfg: ProviderConfig, transport: httpx.BaseTransport | None = None) -> None:
        super().__init__(cfg, transport)
        self.base_url = cfg.base_url or self.BASE

    def _body(self, req: LLMRequest, *, extras: bool) -> dict[str, Any]:
        turns = [
            {"role": "model" if role == "assistant" else "user", "parts": [{"text": text}]} for role, text in (req.history or [])
        ]
        body: dict[str, Any] = {"contents": [*turns, {"role": "user", "parts": [{"text": req.prompt}]}]}
        if req.system:
            body["systemInstruction"] = {"parts": [{"text": req.system}]}
        gen: dict[str, Any] = {}
        if req.temperature is not None:
            gen["temperature"] = req.temperature
        if req.schema:
            gen["responseMimeType"] = "application/json"
            if extras:
                gen["responseJsonSchema"] = req.schema
        if extras and req.thinking == "off":
            gen["thinkingConfig"] = {"thinkingBudget": 0}
        if gen:
            body["generationConfig"] = gen
        return body

    def complete(self, req: LLMRequest) -> LLMResponse:
        key = self.cfg.api_key
        if not key:
            raise ProviderError(f"no {self.cfg.api_key_env} set")
        url = f"/models/{req.model}:generateContent"
        headers = {"x-goog-api-key": key}
        try:
            response = self.client.post(url, json=self._body(req, extras=True), headers=headers, timeout=req.timeout)
            if response.status_code == 400:
                # Some models reject the JSON-schema or thinking settings: ask again without them.
                response = self.client.post(url, json=self._body(req, extras=False), headers=headers, timeout=req.timeout)
        except httpx.HTTPError as exc:
            raise ProviderError(f"network error: {exc}") from exc
        if response.status_code != 200:
            raise ProviderError(
                f"Gemini {response.status_code}: {_error_text(response)}",
                status=response.status_code,
                model_missing=response.status_code == 404,
            )
        data = response.json()
        candidates = data.get("candidates") or []
        if not candidates:
            reason = (data.get("promptFeedback") or {}).get("blockReason", "no answer")
            raise ProviderError(f"Gemini returned no answer ({reason})")
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        if not text:
            raise ProviderError(f"Gemini returned an empty answer ({candidates[0].get('finishReason', 'unknown')})")
        usage = data.get("usageMetadata") or {}
        return LLMResponse(text, usage.get("promptTokenCount"), usage.get("candidatesTokenCount"))

    def list_models(self) -> list[str]:
        try:
            response = self.client.get("/models", headers={"x-goog-api-key": self.cfg.api_key or ""}, params={"pageSize": 200})
        except httpx.HTTPError as exc:
            raise ProviderError(f"network error: {exc}") from exc
        if response.status_code != 200:
            raise ProviderError(f"Gemini {response.status_code}: {_error_text(response)}", status=response.status_code)
        return [
            m["name"].removeprefix("models/")
            for m in response.json().get("models", [])
            if "generateContent" in m.get("supportedGenerationMethods", [])
        ]


class OpenAICompatibleProvider(_HTTPProvider):
    """Any /chat/completions endpoint: OpenAI, OpenRouter, Groq, Ollama (base_url …/v1), LM Studio."""

    def __init__(self, cfg: ProviderConfig, transport: httpx.BaseTransport | None = None) -> None:
        super().__init__(cfg, transport)
        base = cfg.base_url or ("http://localhost:11434/v1" if cfg.kind == "ollama" else "https://api.openai.com/v1")
        self.base_url = base.rstrip("/")

    def complete(self, req: LLMRequest) -> LLMResponse:
        messages = (
            ([{"role": "system", "content": req.system}] if req.system else [])
            + [{"role": role, "content": text} for role, text in (req.history or [])]
            + [{"role": "user", "content": req.prompt}]
        )
        body: dict[str, Any] = {"model": req.model, "messages": messages}
        if req.temperature is not None:
            body["temperature"] = req.temperature
        if req.schema:
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": "result", "schema": req.schema}}
        headers = {"Authorization": f"Bearer {self.cfg.api_key}"} if self.cfg.api_key else {}
        try:
            response = self.client.post("/chat/completions", json=body, headers=headers, timeout=req.timeout)
            if response.status_code == 400 and req.schema:
                body["response_format"] = {"type": "json_object"}
                response = self.client.post("/chat/completions", json=body, headers=headers, timeout=req.timeout)
        except httpx.HTTPError as exc:
            raise ProviderError(f"network error: {exc}") from exc
        if response.status_code != 200:
            raise ProviderError(
                f"{self.cfg.name} {response.status_code}: {_error_text(response)}",
                status=response.status_code,
                model_missing=response.status_code == 404,
            )
        data = response.json()
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("unexpected response shape") from exc
        usage = data.get("usage") or {}
        return LLMResponse(text, usage.get("prompt_tokens"), usage.get("completion_tokens"))


class FakeProvider:
    """For tests: answers come from `script(request)`."""

    def __init__(self, cfg: ProviderConfig, script: Callable[[LLMRequest], str] | None = None) -> None:
        self.cfg = cfg
        self.script = script or (lambda req: json.dumps({}))
        self.requests: list[LLMRequest] = []

    def complete(self, req: LLMRequest) -> LLMResponse:
        self.requests.append(req)
        return LLMResponse(self.script(req), len(req.prompt) // 4, 20)


def make_provider(cfg: ProviderConfig, transport: httpx.BaseTransport | None = None):
    if cfg.kind == "gemini":
        return GeminiProvider(cfg, transport)
    if cfg.kind in {"openai_compatible", "ollama"}:
        return OpenAICompatibleProvider(cfg, transport)
    if cfg.kind == "fake":
        return FakeProvider(cfg)
    raise ValueError(f"unknown provider kind '{cfg.kind}' (use gemini, openai_compatible or ollama)")
