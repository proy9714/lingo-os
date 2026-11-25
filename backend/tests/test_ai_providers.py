"""Choosing between Gemini, Claude and ChatGPT; Claude through the Anthropic SDK; keys saved from Settings."""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

import anthropic
import httpx
import pytest
from pydantic import BaseModel

from app.ai import keys
from app.ai.anthropic_provider import AnthropicProvider, strict_schema
from app.ai.config import parse_ai_config
from app.ai.gateway import AIUnavailable, Gateway
from app.ai.providers import LLMRequest, OpenAICompatibleProvider, ProviderError

ENVS = ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY")
RAW = {
    "providers": {
        "gemini": {"label": "Gemini", "kind": "gemini", "api_key_env": "GEMINI_API_KEY", "models": {"fast": "g-flash", "smart": "g-pro"}},
        "claude": {"label": "Claude", "kind": "anthropic", "api_key_env": "ANTHROPIC_API_KEY", "models": {"fast": "c-1", "smart": "c-1"}},
        "chatgpt": {"label": "ChatGPT", "kind": "openai_compatible", "base_url": "https://api.openai.com/v1",
                    "api_key_env": "OPENAI_API_KEY", "models": {"fast": "o-mini", "smart": "o-big"}},
    },
    "tasks": {"lookup.context_gloss": {"tier": "fast"}, "profile.evolve": {"tier": "smart"}},
}


@pytest.fixture
def no_keys(monkeypatch):
    for env in ENVS:
        monkeypatch.delenv(env, raising=False)
    return monkeypatch


def test_auto_uses_the_first_provider_with_a_key_and_a_choice_overrides_it(client, no_keys) -> None:
    gateway = Gateway(parse_ai_config(RAW), client.app.state.engine)
    with pytest.raises(AIUnavailable, match="GEMINI_API_KEY.*ANTHROPIC_API_KEY.*OPENAI_API_KEY"):
        gateway.route("lookup.context_gloss")

    no_keys.setenv("OPENAI_API_KEY", "sk-test-0000000000")
    no_keys.setenv("ANTHROPIC_API_KEY", "sk-ant-test-000000")
    assert [(n, r.model) for n, r in gateway.route("lookup.context_gloss")] == [("claude", "c-1"), ("chatgpt", "o-mini")]
    assert gateway.route("profile.evolve")[1][1].model == "o-big"

    gateway.set_choice("chatgpt", {"chatgpt": {"fast": "o-custom"}})
    assert [(n, r.model) for n, r in gateway.route("lookup.context_gloss")] == [("chatgpt", "o-custom")]
    assert gateway.status()["provider"] == "ChatGPT"

    gateway.set_choice(None, {"chatgpt": {"fast": None}})  # back to the default model
    assert gateway.route("lookup.context_gloss")[0][1].model == "o-mini"

    gateway.set_choice("gemini")  # chosen but no key: off, with the reason
    with pytest.raises(AIUnavailable, match="GEMINI_API_KEY"):
        gateway.route("lookup.context_gloss")
    with pytest.raises(ValueError):
        gateway.set_choice("mistral")


def test_settings_endpoints_never_send_keys_back(client, no_keys) -> None:
    client.app.state.ai = Gateway(parse_ai_config(RAW), client.app.state.engine)
    saved: list[tuple[str, str]] = []

    def fake_save(path, name, key):  # don't touch the real .env
        saved.append((name, key))
        if key:
            no_keys.setenv(name, key)
        else:
            no_keys.delenv(name, raising=False)

    no_keys.setattr(keys, "save", fake_save)
    secret = "sk-ant-api03-abcdefghijklmnop"
    body = client.put("/api/ai/keys", json={"provider": "claude", "key": f"  {secret} "}).json()
    assert saved == [("ANTHROPIC_API_KEY", secret)]
    assert secret not in json.dumps(body)
    claude = next(p for p in body["providers"] if p["id"] == "claude")
    assert claude["has_key"] and claude["key_hint"] == "…mnop" and body["active"] == "claude"

    assert client.put("/api/ai/keys", json={"provider": "claude", "key": "has space in it 123"}).status_code == 422
    assert client.put("/api/ai/keys", json={"provider": "nope", "key": secret}).status_code == 422

    body = client.put("/api/ai/choice", json={"provider": "chatgpt"}).json()
    assert body["selected"] == "chatgpt" and body["active"] is None  # chosen, but no ChatGPT key yet
    assert client.put("/api/ai/choice", json={"provider": "x"}).status_code == 422
    assert client.get("/api/ai/models", params={"provider": "chatgpt"}).status_code == 409

    client.put("/api/ai/keys", json={"provider": "claude", "key": ""})
    assert saved[-1] == ("ANTHROPIC_API_KEY", "")


def test_keys_are_written_to_the_env_file(tmp_path, no_keys) -> None:
    env = tmp_path / ".env"
    env.write_text("# mine\nGEMINI_API_KEY=old\nOTHER=1\n", encoding="utf-8")
    keys.save(env, "GEMINI_API_KEY", "new-key-1234567890")
    keys.save(env, "OPENAI_API_KEY", "sk-proj-1234567890")
    text = env.read_text(encoding="utf-8")
    assert "GEMINI_API_KEY=new-key-1234567890" in text and "OPENAI_API_KEY=sk-proj-1234567890" in text
    assert "# mine" in text and "OTHER=1" in text and "=old" not in text
    keys.save(env, "GEMINI_API_KEY", "")
    assert "GEMINI_API_KEY" not in env.read_text(encoding="utf-8")
    assert "GEMINI_API_KEY" not in os.environ and os.environ["OPENAI_API_KEY"] == "sk-proj-1234567890"


# ------------------------------------------------------------------ Claude


class FakeMessages:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls: list[dict] = []

    def create(self, **params):
        self.calls.append(params)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


class FakeAnthropic:
    def __init__(self, replies):
        self.messages = FakeMessages(replies)
        self.beta = SimpleNamespace(messages=self.messages)

    def with_options(self, **_):
        return self


def _message(text: str, stop: str = "end_turn"):
    return SimpleNamespace(
        content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)],
        stop_reason=stop, usage=SimpleNamespace(input_tokens=30, output_tokens=12),
    )


def _claude(replies) -> tuple[AnthropicProvider, FakeAnthropic]:
    cfg = parse_ai_config(RAW).providers["claude"]
    fake = FakeAnthropic(replies)
    return AnthropicProvider(cfg, client=fake), fake


def _status_error(cls, status: int):
    response = httpx.Response(status, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))
    return cls("error", response=response, body=None)


def test_claude_request_shape_and_answer() -> None:
    provider, fake = _claude([_message('{"ok": true}')])
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}
    req = LLMRequest("Be brief.", "Ping", "claude-opus-5-5", 0.2, schema, "off", 25,
                     history=[("user", "Hi"), ("assistant", "Hello")])
    response = provider.complete(req)
    assert (response.text, response.tokens_in, response.tokens_out) == ('{"ok": true}', 30, 12)
    call = fake.messages.calls[0]
    assert call["model"] == "claude-opus-5-5" and call["system"] == "Be brief." and "temperature" not in call
    assert [m["role"] for m in call["messages"]] == ["user", "assistant", "user"]
    assert call["output_config"]["effort"] == "low"
    assert call["output_config"]["format"]["schema"]["additionalProperties"] is False
    assert call["fallbacks"] == "default" and call["betas"] == ["server-side-fallback-2026-07-01"]

    provider, fake = _claude([_message("hi")])  # a model without server-side fallbacks: plain request
    provider.complete(LLMRequest("", "Hi", "claude-haiku-5-5"))
    assert "fallbacks" not in fake.messages.calls[0] and "output_config" not in fake.messages.calls[0]


def test_claude_errors_become_provider_errors() -> None:
    provider, fake = _claude([_status_error(anthropic.BadRequestError, 400), _message('{"ok": true}')])
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
    assert provider.complete(LLMRequest("", "Ping", "claude-opus-5-5", schema=schema)).text == '{"ok": true}'
    assert "format" not in fake.messages.calls[1].get("output_config", {})  # retried without the schema

    provider, _ = _claude([_status_error(anthropic.NotFoundError, 404)])
    with pytest.raises(ProviderError) as missing:
        provider.complete(LLMRequest("", "Hi", "claude-nope"))
    assert missing.value.model_missing

    provider, _ = _claude([_status_error(anthropic.AuthenticationError, 401)])
    with pytest.raises(ProviderError, match="not accepted"):
        provider.complete(LLMRequest("", "Hi", "claude-opus-5-5"))

    provider, _ = _claude([_message("", stop="refusal")])
    with pytest.raises(ProviderError, match="declined"):
        provider.complete(LLMRequest("", "Hi", "claude-opus-5-5"))


def test_claude_through_the_gateway(client, no_keys) -> None:
    no_keys.setenv("ANTHROPIC_API_KEY", "sk-ant-test-000000")
    gateway = Gateway(parse_ai_config(RAW), client.app.state.engine)
    gateway.providers["claude"]._client = FakeAnthropic([_message('{"ok": true, "word": "Hallo"}')])

    class Ping(BaseModel):
        ok: bool

    result, meta = gateway.structured("lookup.context_gloss", "ping", {"word": "Hallo"}, Ping, cache=False)
    assert result.ok and meta["provider"] == "claude" and meta["model"] == "c-1"


def test_strict_schema_closes_every_object() -> None:
    schema = {"type": "object", "properties": {"a": {"type": "array", "items": {"type": "object", "properties": {"b": {}}}}}}
    closed = strict_schema(schema)
    assert closed["additionalProperties"] is False and closed["properties"]["a"]["items"]["additionalProperties"] is False


# ------------------------------------------------------------------ ChatGPT


def test_chatgpt_drops_settings_the_model_rejects(no_keys) -> None:
    no_keys.setenv("OPENAI_API_KEY", "sk-test-0000000000")
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        if "temperature" in body:
            return httpx.Response(400, json={"error": {"message": "Unsupported value: 'temperature' does not support 0.2"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}],
                                         "usage": {"prompt_tokens": 9, "completion_tokens": 3}})

    cfg = parse_ai_config(RAW).providers["chatgpt"]
    provider = OpenAICompatibleProvider(cfg, httpx.MockTransport(handler))
    response = provider.complete(LLMRequest("sys", "Ping", "gpt-5-mini", 0.2, {"type": "object"}, "off"))
    assert response.text == '{"ok": true}' and len(bodies) == 2
    assert bodies[0]["reasoning_effort"] == "minimal" and "temperature" not in bodies[1]
    assert bodies[1]["response_format"]["type"] == "json_schema"
