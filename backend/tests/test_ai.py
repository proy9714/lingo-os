from __future__ import annotations

import json

import httpx
import pytest

from app.ai.config import parse_ai_config
from app.ai.gateway import AIUnavailable, Gateway, json_schema, load_prompt, parse_json
from app.ai.providers import FakeProvider, GeminiProvider, LLMRequest
from app.services.explain import ContextGloss, GrammarBreakdown


def fake_gateway(client, script, **extra) -> tuple[Gateway, FakeProvider]:
    raw = {
        "providers": {"cloud": {"kind": "fake"}, **extra.pop("providers", {})},
        "tasks": {
            "lookup.context_gloss": {"use": "cloud", "model": "fake-1", **extra.pop("gloss", {})},
            "lookup.grammar": {"use": "cloud", "model": "fake-1"},
        },
        **extra,
    }
    gateway = Gateway(parse_ai_config(raw), client.app.state.engine)
    fake = gateway.providers["cloud"]
    fake.script = script
    client.app.state.ai = gateway
    return gateway, fake


GLOSS = {"meaning": "neighbours", "sense": 0, "note": "Plural after 'welche'.", "translation": "...which neighbours moved."}


def test_without_a_key_everything_degrades_with_a_reason(client, monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    gateway = Gateway(parse_ai_config({"providers": {"cloud": {"kind": "gemini", "api_key_env": "GEMINI_API_KEY"}},
                                       "tasks": {"lookup.context_gloss": {"use": "cloud", "model": "m"}}}),
                      client.app.state.engine)
    client.app.state.ai = gateway
    status = client.get("/api/ai/status").json()
    assert status["context"] == {"enabled": False, "reason": "no GEMINI_API_KEY in .env", "local_only": False}
    response = client.post("/api/ai/gloss", json={"lang": "de", "sentence": "Hallo Welt.", "surface": "Welt", "lemma": "Welt"})
    assert response.status_code == 503
    assert "GEMINI_API_KEY" in response.json()["detail"]
    assert client.post("/api/ai/grammar", json={"lang": "de", "sentence": "Hallo."}).status_code == 503  # no route at all


def test_gloss_is_cached_and_logged(client) -> None:
    _, fake = fake_gateway(client, lambda req: json.dumps(GLOSS))
    body = {"lang": "de", "sentence": "Welche Nachbarn umgezogen sind.", "surface": "Nachbarn", "lemma": "Nachbar", "pos": "NOUN"}
    first = client.post("/api/ai/gloss", json=body).json()
    assert first["meaning"] == "neighbours" and first["cached"] is False
    assert "Nachbarn" in fake.requests[0].prompt and fake.requests[0].schema["properties"]["meaning"]["type"] == "string"
    second = client.post("/api/ai/gloss", json=body).json()
    assert second["cached"] is True and len(fake.requests) == 1
    usage = client.get("/api/ai/usage").json()
    assert usage["calls"] == 1 and usage["cache_hits"] == 1


def test_invalid_json_gets_one_repair_attempt(client) -> None:
    answers = iter(["not json at all", "```json\n" + json.dumps(GLOSS) + "\n```"])
    _, fake = fake_gateway(client, lambda req: next(answers))
    body = {"lang": "de", "sentence": "Hallo Welt.", "surface": "Welt", "lemma": "Welt"}
    assert client.post("/api/ai/gloss", json=body).json()["meaning"] == "neighbours"
    assert len(fake.requests) == 2 and "could not be used" in fake.requests[1].prompt


def test_fallback_provider_answers_when_the_first_fails(client) -> None:
    raw = {
        "providers": {"cloud": {"kind": "fake"}, "local": {"kind": "fake"}},
        "tasks": {"lookup.context_gloss": {"use": "cloud", "model": "a", "fallback": ["local"]}},
    }
    gateway = Gateway(parse_ai_config(raw), client.app.state.engine)
    gateway.providers["cloud"].script = lambda req: "broken"
    gateway.providers["local"].script = lambda req: json.dumps(GLOSS)
    result, meta = gateway.structured("lookup.context_gloss", "context_gloss", _vars(), ContextGloss)
    assert meta["provider"] == "local" and result.sense == 0


def test_local_only_blocks_cloud_providers(client, monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    raw = {
        "local_only": True,
        "providers": {"cloud": {"kind": "gemini", "api_key_env": "GEMINI_API_KEY"}},
        "tasks": {"lookup.context_gloss": {"use": "cloud", "model": "m"}},
    }
    gateway = Gateway(parse_ai_config(raw), client.app.state.engine)
    with pytest.raises(AIUnavailable, match="local-only"):
        gateway.route("lookup.context_gloss")


def test_grammar_keeps_only_parts_found_in_the_sentence(client) -> None:
    answer = {
        "translation": "I call my grandparents.",
        "parts": [{"text": "rufe", "gloss": "call", "role": "verb"}, {"text": "invented", "gloss": "x", "role": "y"}],
        "points": [{"name": "separable verb anrufen", "explanation": "an goes to the end.", "level": "A2"}],
    }
    fake_gateway(client, lambda req: json.dumps(answer))
    result = client.post("/api/ai/grammar", json={"lang": "de", "sentence": "Ich rufe meine Großeltern an."}).json()
    assert [p["text"] for p in result["parts"]] == ["rufe"]
    assert result["points"][0]["level"] == "A2"


def test_gemini_request_and_response_shape(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "secret")
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={
            "candidates": [{"content": {"parts": [{"text": "thinking...", "thought": True}, {"text": '{"ok": true}'}]}}],
            "usageMetadata": {"promptTokenCount": 12, "candidatesTokenCount": 3},
        })

    cfg = parse_ai_config({"providers": {"cloud": {"kind": "gemini", "api_key_env": "GEMINI_API_KEY"}}}).providers["cloud"]
    provider = GeminiProvider(cfg, httpx.MockTransport(handler))
    response = provider.complete(LLMRequest("sys", "hi", "gemini-x", 0.2, {"type": "object"}, "off", 5))
    assert (response.text, response.tokens_in, response.tokens_out) == ('{"ok": true}', 12, 3)
    request = seen[0]
    assert request.url.path.endswith("/models/gemini-x:generateContent")
    assert request.headers["x-goog-api-key"] == "secret"
    body = json.loads(request.content)
    assert body["systemInstruction"]["parts"][0]["text"] == "sys"
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 0}


def test_gemini_retries_without_optional_fields_on_400(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "secret")
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        if len(bodies) == 1:
            return httpx.Response(400, json={"error": {"message": "Unknown name responseJsonSchema"}})
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "{}"}]}}]})

    cfg = parse_ai_config({"providers": {"cloud": {"kind": "gemini", "api_key_env": "GEMINI_API_KEY"}}}).providers["cloud"]
    GeminiProvider(cfg, httpx.MockTransport(handler)).complete(LLMRequest("", "hi", "m", None, {"type": "object"}, "off"))
    assert "responseJsonSchema" in bodies[0]["generationConfig"]
    assert "responseJsonSchema" not in bodies[1]["generationConfig"] and "thinkingConfig" not in bodies[1]["generationConfig"]


def test_prompts_and_schema_helpers() -> None:
    prompt = load_prompt("context_gloss")
    assert prompt.version >= 1 and "${sentence}" in prompt.user and prompt.system
    schema = json_schema(GrammarBreakdown)
    assert "$defs" not in json.dumps(schema) and schema["properties"]["parts"]["items"]["properties"]["text"]["type"] == "string"
    assert parse_json('Sure! {"a": 1} hope that helps') == {"a": 1}


def _vars() -> dict[str, str]:
    return {"language": "German", "sentence": "s", "surface": "w", "lemma": "w", "pos": "noun", "senses": "0: x"}
