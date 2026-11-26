"""Podcasts: search the directory, follow shows, list their episodes, check for new ones."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import Connection

from app.api.deps import get_conn, require_language
from app.ingest.feeds import FeedError
from app.services import podcasts, recommend

router = APIRouter(prefix="/api/podcasts", tags=["podcasts"])


class Subscribe(BaseModel):
    lang: str = Field(min_length=2, max_length=8)
    feed_url: str = Field(min_length=8, max_length=1000)


class Refresh(BaseModel):
    lang: str = Field(min_length=2, max_length=8)
    force: bool = False


@router.get("/search")
def search(lang: str = Query(..., min_length=2, max_length=8), q: str = Query("", max_length=200), conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    """Shows in the Apple Podcasts directory (learner podcasts in your language when there's no search)."""
    require_language(conn, lang)
    followed = {s["feed_url"] for s in podcasts.shows(conn, lang)}
    return {"results": [{**r, "following": r["feed_url"] in followed} for r in podcasts.search(lang, q)]}


@router.get("")
def shows(lang: str = Query(..., min_length=2, max_length=8), conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    require_language(conn, lang)
    return {"shows": podcasts.shows(conn, lang)}


@router.post("/subscribe")
def subscribe(body: Subscribe, conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    require_language(conn, body.lang)
    try:
        result = podcasts.subscribe(conn, body.lang, body.feed_url)
    except (podcasts.PodcastError, FeedError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    recommend.invalidate()
    return result


@router.delete("/{collection_id}")
def unsubscribe(collection_id: int, conn: Connection = Depends(get_conn)) -> dict[str, bool]:
    if not podcasts.unsubscribe(conn, collection_id):
        raise HTTPException(status_code=404, detail="no such show")
    recommend.invalidate()
    return {"unsubscribed": True}


@router.get("/{collection_id}/episodes")
def episodes(collection_id: int, offset: int = Query(0, ge=0), limit: int = Query(30, ge=1, le=100), conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    try:
        return podcasts.episodes(conn, collection_id, offset, limit)
    except podcasts.PodcastError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/refresh")
def refresh(body: Refresh, conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    """Check the shows you follow for new episodes (each at most every 12 hours unless forced)."""
    require_language(conn, body.lang)
    result = podcasts.refresh(conn, body.lang, force=body.force)
    if result["added"]:
        recommend.invalidate()
    return result
