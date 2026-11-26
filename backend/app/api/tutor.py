"""Tutor conversations. Needs an AI provider; without one every call explains how to turn it on."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import Connection, Engine

from app.ai.gateway import AIUnavailable, Gateway
from app.api.ai import get_ai
from app.api.deps import get_conn, require_language
from app.jobs import tutor_review  # noqa: F401 - registers the review job
from app.jobs.runner import get_job
from app.services import tutor

router = APIRouter(prefix="/api/tutor", tags=["tutor"])


def get_engine(request: Request) -> Engine:
    return request.app.state.engine


class StartRequest(BaseModel):
    lang: str = Field(min_length=2, max_length=8)
    mode: str = Field(pattern="^(conversation|roleplay|content_discussion|correction_drill)$")
    scenario: str | None = Field(default=None, max_length=40)
    content_item_id: int | None = None


class Say(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    input_mode: str = Field(default="text", pattern="^(text|voice)$")


def _fail(exc: Exception) -> HTTPException:
    if isinstance(exc, AIUnavailable):
        return HTTPException(status_code=503, detail=f"The tutor needs an AI provider: {exc}")
    return HTTPException(status_code=422, detail=str(exc))


@router.get("/options")
def options(lang: str = Query(..., min_length=2, max_length=8), conn: Connection = Depends(get_conn), ai: Gateway = Depends(get_ai)) -> dict[str, Any]:
    require_language(conn, lang)
    return {
        "status": ai.status("tutor.chat"),
        "scenarios": tutor.SCENARIOS.get(lang, []),
        "weak_grammar": tutor._weak_grammar(conn, lang),
        "focus_words": tutor._focus_words(conn, lang),
        "speech_rate": float(tutor.active_instructions(conn, lang)["style"].get("speech_rate", 0.9)),
    }


@router.get("/recent-items")
def recent_items(lang: str = Query(..., min_length=2, max_length=8), conn: Connection = Depends(get_conn)) -> list[dict[str, Any]]:
    """The last 10 videos or texts you watched or read, for "talk about something you watched or read"."""
    require_language(conn, lang)
    return tutor.recent_items(conn, lang)


@router.get("/sessions")
def sessions(lang: str = Query(..., min_length=2, max_length=8), conn: Connection = Depends(get_conn)) -> list[dict[str, Any]]:
    return tutor.list_sessions(conn, lang)


@router.post("/sessions", status_code=201)
def start(body: StartRequest, engine: Engine = Depends(get_engine), ai: Gateway = Depends(get_ai)) -> dict[str, Any]:
    with engine.connect() as conn:
        require_language(conn, body.lang)
    try:
        return tutor.start_session(ai, engine, body.lang, body.mode, body.scenario, body.content_item_id)
    except (AIUnavailable, tutor.TutorError) as exc:
        raise _fail(exc) from exc


@router.get("/sessions/{session_id}")
def session(session_id: int, conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    try:
        return tutor.get_session(conn, session_id)
    except tutor.TutorError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/sessions/{session_id}/messages")
def say(session_id: int, body: Say, engine: Engine = Depends(get_engine), ai: Gateway = Depends(get_ai)) -> dict[str, Any]:
    try:
        return tutor.reply(ai, engine, session_id, body.text, body.input_mode)
    except (AIUnavailable, tutor.TutorError) as exc:
        raise _fail(exc) from exc


@router.post("/sessions/{session_id}/messages/stream")
def say_streaming(session_id: int, body: Say, engine: Engine = Depends(get_engine), ai: Gateway = Depends(get_ai)):  # noqa: ANN201
    """The reply as it's written, as server-sent events: `delta` pieces, then `done` (or `error`)."""
    import json as _json

    from fastapi.responses import StreamingResponse

    def events():  # noqa: ANN202
        try:
            for event in tutor.reply_stream(ai, engine, session_id, body.text, body.input_mode):
                yield f"data: {_json.dumps(event, ensure_ascii=False)}\n\n"
        except (AIUnavailable, tutor.TutorError) as exc:
            yield f"data: {_json.dumps({'error': _fail(exc).detail}, ensure_ascii=False)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@router.post("/sessions/{session_id}/end")
def end(session_id: int, conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    return tutor.end_session(conn, session_id)


@router.get("/jobs/{job_id}")
def review_job(job_id: int, conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    job = get_job(conn, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="no such job")
    return job


@router.get("/reference/{lang}/weak-spots")
def grammar_weak_spots(lang: str, conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    """Only the part of the grammar page that is about you: what the tutor noticed you still slip on.

    The reference itself never changes between versions of the app, so the app carries it with it
    (frontend/src/generated/grammar, written by `lingo grammar export`) and only asks for this.
    """
    from app.services import grammar

    require_language(conn, lang)
    try:
        return {"language": lang, "weak_spots": grammar.weak_spots(conn, lang)}
    except grammar.GrammarError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/reference/{lang}")
def grammar_reference(lang: str, conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    """The grammar overview for a language, with the tutor's notes on what you still slip on."""
    from app.services import grammar

    require_language(conn, lang)
    try:
        return {**grammar.reference(lang), "weak_spots": grammar.weak_spots(conn, lang)}
    except grammar.GrammarError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/grammar")
def grammar(lang: str = Query(..., min_length=2, max_length=8), conn: Connection = Depends(get_conn)) -> list[dict[str, Any]]:
    return tutor.grammar_overview(conn, lang)
