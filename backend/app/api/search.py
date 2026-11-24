"""Search YouTube or the news for anything; every result is rated for your level as it's measured."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import Connection

from app.api.deps import get_cfg, get_conn, require_language
from app.config import AppConfig
from app.services import search

router = APIRouter(prefix="/api/search", tags=["search"])


class SearchRequest(BaseModel):
    lang: str = Field(min_length=2, max_length=8)
    kind: str = Field(pattern="^(video|article)$")
    q: str = Field(min_length=1, max_length=200)


@router.post("")
def start(body: SearchRequest, request: Request, conn: Connection = Depends(get_conn), cfg: AppConfig = Depends(get_cfg)) -> dict[str, Any]:
    require_language(conn, body.lang)
    try:
        return search.start(request.app.state.engine, cfg, body.lang, body.kind, body.q)
    except search.SearchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/{search_id}")
def results(search_id: str, request: Request) -> dict[str, Any]:
    """The search's results so far; poll while `pending` > 0."""
    try:
        return search.snapshot(request.app.state.engine, search_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="That search has expired: search again.") from exc
