"""AI endpoints. All of them degrade to a 503 with a plain reason when no provider is available."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import Connection

from app.ai.gateway import AIUnavailable, Gateway
from app.api.deps import get_conn, get_dict_conn, require_language
from app.services import explain

router = APIRouter(prefix="/api/ai", tags=["ai"])


def get_ai(request: Request) -> Gateway:
    return request.app.state.ai


class GlossRequest(BaseModel):
    lang: str = Field(min_length=2, max_length=8)
    sentence: str = Field(min_length=1, max_length=1000)
    surface: str = Field(min_length=1, max_length=100)
    lemma: str = Field(min_length=1, max_length=200)
    pos: str = Field(default="", max_length=16)
    reading: str = Field(default="", max_length=200)


class GrammarRequest(BaseModel):
    lang: str = Field(min_length=2, max_length=8)
    sentence: str = Field(min_length=1, max_length=1000)


class Ping(BaseModel):
    ok: bool
    word: str = ""


def _unavailable(exc: AIUnavailable) -> HTTPException:
    return HTTPException(status_code=503, detail=f"AI explanations are off: {exc}")


@router.get("/status")
def status(ai: Gateway = Depends(get_ai)) -> dict[str, Any]:
    return {"context": ai.status("lookup.context_gloss"), "grammar": ai.status("lookup.grammar")}


@router.get("/usage")
def usage(days: int = Query(30, ge=1, le=365), ai: Gateway = Depends(get_ai)) -> dict[str, Any]:
    return ai.usage(days)


@router.post("/test")
def test(ai: Gateway = Depends(get_ai)) -> dict[str, Any]:
    """One tiny uncached call to check the key and model work."""
    try:
        result, meta = ai.structured("lookup.context_gloss", "ping", {"word": "Hallo"}, Ping, cache=False)
    except AIUnavailable as exc:
        raise _unavailable(exc) from exc
    return {"ok": result.ok, **meta}


@router.post("/gloss")
def gloss(
    body: GlossRequest,
    conn: Connection = Depends(get_conn),
    dict_conn: Connection = Depends(get_dict_conn),
    ai: Gateway = Depends(get_ai),
) -> dict[str, Any]:
    require_language(conn, body.lang)
    try:
        return explain.context_gloss(
            ai, conn, dict_conn, lang=body.lang, sentence=body.sentence, surface=body.surface, lemma=body.lemma,
            pos=body.pos, reading=body.reading,
        )
    except AIUnavailable as exc:
        raise _unavailable(exc) from exc


@router.post("/grammar")
def grammar(body: GrammarRequest, conn: Connection = Depends(get_conn), ai: Gateway = Depends(get_ai)) -> dict[str, Any]:
    require_language(conn, body.lang)
    try:
        return explain.grammar_breakdown(ai, conn, lang=body.lang, sentence=body.sentence)
    except AIUnavailable as exc:
        raise _unavailable(exc) from exc
