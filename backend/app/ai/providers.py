"""Provider adapters. Each turns one request into one HTTP call and reports token counts."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
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

    def stream(self, req: LLMRequest) -> Iterator[str]:
        """The answer in pieces as it's written (server-sent events)."""
        key = self.cfg.api_key
        if not key:
            raise ProviderError(f"no {self.cfg.api_key_env} set")
        url = f"/models/{req.model}:streamGenerateContent"
        try:
            with self.client.stream("POST", url, params={"alt": "sse"}, json=self._body(req, extras=True),
                                    headers={"x-goog-api-key": key}, timeout=req.timeout) as response:
                if response.status_code != 200:
                    response.read()
                    raise ProviderError(f"Gemini {response.status_code}: {_error_text(response)}", status=response.status_code,
                                        model_missing=response.status_code == 404)
                for line in response.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = json.loads(line[5:].strip() or "{}")
                    for candidate in data.get("candidates") or []:
                        for part in (candidate.get("content") or {}).get("parts") or []:
                            if part.get("text") and not part.get("thought"):
                                yield part["text"]
        except httpx.HTTPError as exc:
            raise ProviderError(f"network error: {exc}") from exc

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
        if req.thinking == "off" and self.is_openai:
            body["reasoning_effort"] = "minimal"  # reasoning models: answer quickly
        if req.schema:
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": "result", "schema": req.schema}}
        headers = {"Authorization": f"Bearer {self.cfg.api_key}"} if self.cfg.api_key else {}
        try:
            response = self.client.post("/chat/completions", json=body, headers=headers, timeout=req.timeout)
            # Models differ in what they accept (newer OpenAI models take no temperature, older ones no
            # reasoning_effort): drop what the error names, or simplify the JSON request, and ask again.
            for _ in range(3):
                if response.status_code != 400:
                    break
                error = _error_text(response)
                dropped = next((k for k in ("temperature", "reasoning_effort") if k in body and k in error), None)
                if dropped:
                    body.pop(dropped)
                elif body.get("response_format", {}).get("type") == "json_schema":
                    body["response_format"] = {"type": "json_object"}
                else:
                    break
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

    def stream(self, req: LLMRequest) -> Iterator[str]:
        """The answer in pieces as it's written (stream: true)."""
        messages = (
            ([{"role": "system", "content": req.system}] if req.system else [])
            + [{"role": role, "content": text} for role, text in (req.history or [])]
            + [{"role": "user", "content": req.prompt}]
        )
        body: dict[str, Any] = {"model": req.model, "messages": messages, "stream": True}
        if req.temperature is not None and not self.is_openai:  # newer OpenAI models take only the default
            body["temperature"] = req.temperature
        headers = {"Authorization": f"Bearer {self.cfg.api_key}"} if self.cfg.api_key else {}
        try:
            with self.client.stream("POST", "/chat/completions", json=body, headers=headers, timeout=req.timeout) as response:
                if response.status_code != 200:
                    response.read()
                    raise ProviderError(f"{self.cfg.name} {response.status_code}: {_error_text(response)}", status=response.status_code,
                                        model_missing=response.status_code == 404)
                for line in response.iter_lines():
                    if not line.startswith("data:") or line.strip() == "data: [DONE]":
                        continue
                    data = json.loads(line[5:].strip() or "{}")
                    for choice in data.get("choices") or []:
                        piece = (choice.get("delta") or {}).get("content")
                        if piece:
                            yield piece
        except httpx.HTTPError as exc:
            raise ProviderError(f"network error: {exc}") from exc

    @property
    def is_openai(self) -> bool:
        return "api.openai.com" in self.base_url

    def list_models(self) -> list[str]:
        headers = {"Authorization": f"Bearer {self.cfg.api_key}"} if self.cfg.api_key else {}
        try:
            response = self.client.get("/models", headers=headers)
        except httpx.HTTPError as exc:
            raise ProviderError(f"network error: {exc}") from exc
        if response.status_code != 200:
            raise ProviderError(f"{self.cfg.name} {response.status_code}: {_error_text(response)}", status=response.status_code)
        ids = sorted(m["id"] for m in response.json().get("data", []) if isinstance(m, dict) and m.get("id"))
        if self.is_openai:  # only chat models: not embeddings, images, speech, moderation
            skip = ("embedding", "whisper", "tts", "dall-e", "image", "moderation", "audio", "realtime", "transcribe", "search")
            ids = [i for i in ids if i.startswith(("gpt-", "o1", "o3", "o4", "chatgpt")) and not any(s in i for s in skip)]
        return ids


class FakeProvider:
    """For tests: answers come from `script(request)`."""

    def __init__(self, cfg: ProviderConfig, script: Callable[[LLMRequest], str] | None = None) -> None:
        self.cfg = cfg
        self.script = script or (lambda req: json.dumps({}))
        self.requests: list[LLMRequest] = []

    def complete(self, req: LLMRequest) -> LLMResponse:
        self.requests.append(req)
        return LLMResponse(self.script(req), len(req.prompt) // 4, 20)

    def stream(self, req: LLMRequest) -> Iterator[str]:
        text = self.complete(req).text
        for start in range(0, len(text), 7):
            yield text[start : start + 7]


def make_provider(cfg: ProviderConfig, transport: httpx.BaseTransport | None = None):
    if cfg.kind == "gemini":
        return GeminiProvider(cfg, transport)
    if cfg.kind == "anthropic":
        from app.ai.anthropic_provider import AnthropicProvider

        return AnthropicProvider(cfg)
    if cfg.kind in {"openai_compatible", "ollama"}:
        return OpenAICompatibleProvider(cfg, transport)
    if cfg.kind == "fake":
        return FakeProvider(cfg)
    raise ValueError(f"unknown provider kind '{cfg.kind}' (use gemini, anthropic, openai_compatible or ollama)")
