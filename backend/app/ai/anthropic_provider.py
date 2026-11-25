"""Claude through Anthropic's official Python SDK (the `anthropic` package)."""

from __future__ import annotations

from typing import Any

import anthropic

from app.ai.config import ProviderConfig
from app.ai.providers import LLMRequest, LLMResponse, ProviderError

# Models that accept server-side refusal fallbacks: if a safety check declines a request, the API answers it with
# another Claude model inside the same call instead of returning nothing.
FALLBACK_MODELS = ("claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-fable-5-2", "claude-fable-5-1")
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_TOKENS = 16000


def strict_schema(node: Any) -> Any:
    """Claude's structured outputs need every object closed (`additionalProperties: false`)."""
    if isinstance(node, dict):
        out = {k: strict_schema(v) for k, v in node.items()}
        if out.get("type") == "object" and "properties" in out:
            out["additionalProperties"] = False
        return out
    if isinstance(node, list):
        return [strict_schema(v) for v in node]
    return node


class AnthropicProvider:
    """One request becomes one Messages API call. Clients are made per key, so a key pasted in Settings works at once."""

    def __init__(self, cfg: ProviderConfig, client: Any | None = None) -> None:
        self.cfg = cfg
        self._client = client  # tests pass a stand-in
        self._clients: dict[str, anthropic.Anthropic] = {}

    def client(self) -> Any:
        if self._client is not None:
            return self._client
        key = self.cfg.api_key
        if not key:
            raise ProviderError(f"no {self.cfg.api_key_env} set")
        if key not in self._clients:
            kwargs: dict[str, Any] = {"api_key": key, "max_retries": 1}
            if self.cfg.base_url:
                kwargs["base_url"] = self.cfg.base_url
            self._clients = {key: anthropic.Anthropic(**kwargs)}  # keep only the current key's client
        return self._clients[key]

    def params(self, req: LLMRequest, *, structured: bool = True) -> dict[str, Any]:
        messages = [{"role": role, "content": text} for role, text in (req.history or [])]
        messages.append({"role": "user", "content": req.prompt})
        params: dict[str, Any] = {"model": req.model, "max_tokens": MAX_TOKENS, "messages": messages}
        if req.system:
            params["system"] = req.system
        output: dict[str, Any] = {}
        if req.thinking == "off":
            output["effort"] = "low"  # quick look-ups: current Claude models always think, so ask for the least
        if req.schema and structured:
            output["format"] = {"type": "json_schema", "schema": strict_schema(req.schema)}
        if output:
            params["output_config"] = output
        # temperature is left out: current Claude models reject sampling parameters
        return params

    def _create(self, client: Any, params: dict[str, Any], timeout: float) -> Any:
        api = client.with_options(timeout=timeout)
        if params["model"] in FALLBACK_MODELS:
            return api.beta.messages.create(**params, betas=[FALLBACK_BETA], fallbacks="default")
        return api.messages.create(**params)

    def complete(self, req: LLMRequest) -> LLMResponse:
        client = self.client()
        params = self.params(req)
        try:
            try:
                message = self._create(client, params, req.timeout)
            except anthropic.BadRequestError:
                if "output_config" not in params or "format" not in params["output_config"]:
                    raise
                # a schema the structured-output checker won't take: ask again and rely on the prompt's JSON instructions
                message = self._create(client, self.params(req, structured=False), req.timeout)
        except anthropic.NotFoundError as exc:
            raise ProviderError(f"Claude: model '{req.model}' not found", status=404, model_missing=True) from exc
        except anthropic.AuthenticationError as exc:
            raise ProviderError("Claude: the API key was not accepted", status=401) from exc
        except anthropic.RateLimitError as exc:
            raise ProviderError("Claude: rate limit or credit limit reached; try again later", status=429) from exc
        except anthropic.APIStatusError as exc:
            raise ProviderError(f"Claude {exc.status_code}: {exc.message}"[:300], status=exc.status_code) from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderError(f"network error: {exc}") from exc
        if message.stop_reason == "refusal":
            raise ProviderError("Claude declined to answer this one")
        text = "".join(block.text for block in message.content if block.type == "text")
        if not text:
            raise ProviderError(f"Claude returned an empty answer ({message.stop_reason})")
        usage = message.usage
        return LLMResponse(text, getattr(usage, "input_tokens", None), getattr(usage, "output_tokens", None))

    def list_models(self) -> list[str]:
        try:
            return [model.id for model in self.client().models.list()]
        except anthropic.AuthenticationError as exc:
            raise ProviderError("Claude: the API key was not accepted", status=401) from exc
        except anthropic.APIStatusError as exc:
            raise ProviderError(f"Claude {exc.status_code}: {exc.message}"[:300], status=exc.status_code) from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderError(f"network error: {exc}") from exc
