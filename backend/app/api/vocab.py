from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import Connection

from app.api.deps import get_conn, require_language
from app.languages.frequency import rank_of
from app.services import vocab

router = APIRouter(prefix="/api/vocab", tags=["vocab"])

Status = Literal["seen", "learning", "familiar", "known", "ignored"]


class Context(BaseModel):
    sentence: str = Field(min_length=1, max_length=1000)
    surface: str = Field(default="", max_length=100)
    locator: str | None = Field(default=None, max_length=200)
    content_item_id: int | None = None


class StatusRequest(BaseModel):
    lang: str = Field(min_length=2, max_length=8)
    lemma: str = Field(min_length=1, max_length=200)
    reading: str = Field(default="", max_length=200)
    pos: str = Field(default="", max_length=16)
    status: Status
    save: bool = False
    context: Context | None = None


class WordPatch(BaseModel):
    status: Status | None = None
    note: str | None = Field(default=None, max_length=2000)
    gloss: str | None = Field(default=None, max_length=300)


@router.post("/status")
def set_status(body: StatusRequest, conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    require_language(conn, body.lang)
    return vocab.set_status(
        conn,
        body.lang,
        body.lemma,
        body.reading,
        body.status,
        pos=body.pos,
        rank=rank_of(body.lang, body.lemma),
        save=body.save,
        context=body.context.model_dump() if body.context else None,
    )


@router.get("/words")
def list_words(
    lang: str = Query(..., min_length=2, max_length=8),
    status: str | None = Query(None, pattern="^(seen|learning|familiar|known|ignored|saved)$"),
    q: str | None = Query(None, max_length=100),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    conn: Connection = Depends(get_conn),
) -> dict[str, Any]:
    require_language(conn, lang)
    return vocab.list_words(conn, lang, status=status, q=q, limit=limit, offset=offset)


@router.get("/summary")
def summary(lang: str = Query(..., min_length=2, max_length=8), conn: Connection = Depends(get_conn)) -> dict[str, int]:
    require_language(conn, lang)
    return vocab.summary(conn, lang)


@router.get("/words/{lexeme_id}")
def word(lexeme_id: int, conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    try:
        state = vocab.word_state(conn, lexeme_id)
    except vocab.VocabError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {**state, "contexts_list": vocab.contexts(conn, lexeme_id)}


@router.patch("/words/{lexeme_id}")
def patch_word(lexeme_id: int, body: WordPatch, conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    try:
        return vocab.update_word(conn, lexeme_id, status=body.status, note=body.note, gloss=body.gloss)
    except vocab.VocabError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
