from __future__ import annotations

import json

from sqlalchemy import text

from app.ai.config import parse_ai_config
from app.ai.gateway import Gateway
from app.ai.providers import LLMRequest
from app.services.tutor import postprocess

HARD = "Die Quintessenz deiner Ausführungen erscheint mir epistemologisch fragwürdig und redundant."
EASY = "Hallo! Wie geht es dir heute?"


def tutor_gateway(client, script) -> Gateway:
    raw = {
        "providers": {"cloud": {"kind": "fake"}},
        "tasks": {t: {"use": "cloud", "model": "fake-1"} for t in ("tutor.chat", "tutor.postprocess")},
    }
    gateway = Gateway(parse_ai_config(raw), client.app.state.engine)
    gateway.providers["cloud"].script = script
    client.app.state.ai = gateway
    return gateway


def test_without_ai_the_tutor_explains_why(client, monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    client.app.state.ai = Gateway(
        parse_ai_config({"providers": {"cloud": {"kind": "gemini", "api_key_env": "GEMINI_API_KEY"}},
                         "tasks": {"tutor.chat": {"use": "cloud", "model": "m"}}}),
        client.app.state.engine,
    )
    options = client.get("/api/tutor/options", params={"lang": "de"}).json()
    assert options["status"]["enabled"] is False and len(options["scenarios"]) == 4
    response = client.post("/api/tutor/sessions", json={"lang": "de", "mode": "conversation"})
    assert response.status_code == 503 and "GEMINI_API_KEY" in response.json()["detail"]


def test_conversation_with_vocabulary_governor(client) -> None:
    def script(req: LLMRequest) -> str:
        if "Rewrite this" in req.prompt:
            return EASY
        return HARD if not req.history or len(req.history) == 1 else "**Super!** Was machst du am Wochenende?"

    gateway = tutor_gateway(client, script)
    fake = gateway.providers["cloud"]
    session = client.post("/api/tutor/sessions", json={"lang": "de", "mode": "conversation"}).json()
    opening = session["messages"][0]
    assert opening["role"] == "assistant" and opening["text"] == EASY  # the hard opening was simplified
    assert opening["coverage"] is not None and any(t["display"] == "Hallo" for t in opening["tokens"])
    assert any("Rewrite this" in r.prompt for r in fake.requests)
    system = fake.requests[0].system
    assert "German" in system and "du" in system and "Free conversation" in system

    turn = client.post(f"/api/tutor/sessions/{session['id']}/messages", json={"text": "Mir geht gut, danke.", "input_mode": "voice"}).json()
    assert turn["user"]["text"] == "Mir geht gut, danke." and turn["user"]["input_mode"] == "voice"
    assert turn["assistant"]["text"] == "Super! Was machst du am Wochenende?"  # markdown stripped
    history = next(r.history for r in reversed(fake.requests) if r.history)
    assert history[0][0] == "user" and history[1] == ("assistant", EASY)

    listed = client.get("/api/tutor/sessions", params={"lang": "de"}).json()
    assert listed[0]["id"] == session["id"] and listed[0]["turns"] == 1


def test_roleplay_needs_a_known_scenario(client) -> None:
    tutor_gateway(client, lambda req: EASY)
    bad = client.post("/api/tutor/sessions", json={"lang": "es", "mode": "roleplay", "scenario": "nope"})
    assert bad.status_code == 422
    good = client.post("/api/tutor/sessions", json={"lang": "es", "mode": "roleplay", "scenario": "cafe"}).json()
    assert good["scenario"] == "cafe"


def test_review_records_corrections_and_grammar(client) -> None:
    review = {
        "summary": "You talked about your weekend.",
        "strengths": ["Good questions"],
        "corrections": [
            {"turn": 1, "original": "Ich habe nach Berlin gefahren.", "corrected": "Ich bin nach Berlin gefahren.",
             "explanation": "Verbs of motion take sein.", "grammar": "Perfekt mit sein"},
            {"turn": 2, "original": "same", "corrected": "same", "explanation": "", "grammar": ""},
        ],
        "words_used": [],
    }

    def script(req: LLMRequest) -> str:
        return json.dumps(review) if req.schema else EASY

    gateway = tutor_gateway(client, script)
    session = client.post("/api/tutor/sessions", json={"lang": "de", "mode": "conversation"}).json()
    for said in ("Ich habe nach Berlin gefahren.", "same"):
        client.post(f"/api/tutor/sessions/{session['id']}/messages", json={"text": said})
    ended = client.post(f"/api/tutor/sessions/{session['id']}/end").json()
    assert ended["review_job"] > 0

    result = postprocess(gateway, client.app.state.engine, session["id"])
    assert result["corrections"] == 1
    data = client.get(f"/api/tutor/sessions/{session['id']}").json()
    assert data["postprocessed"] == 1 and "weekend" in data["summary_md"] and "Good questions" in data["summary_md"]
    first_user = next(m for m in data["messages"] if m["role"] == "user")
    assert first_user["corrections"][0]["corrected"] == "Ich bin nach Berlin gefahren."

    grammar = client.get("/api/tutor/grammar", params={"lang": "de"}).json()
    assert grammar[0]["title"] == "Perfekt mit sein" and grammar[0]["errors"] == 1 and grammar[0]["status"] == "practicing"
    # the weak point now feeds the next session's prompt
    client.post(f"/api/tutor/sessions", json={"lang": "de", "mode": "correction_drill"})
    assert any("Practice session for: Perfekt mit sein" in r.system for r in gateway.providers["cloud"].requests)
    assert postprocess(gateway, client.app.state.engine, session["id"])["skipped"] == "already reviewed"
    with client.app.state.engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM grammar_evidence")).scalar() == 1
    assert client.post(f"/api/tutor/sessions/{session['id']}/messages", json={"text": "noch was"}).status_code == 422
