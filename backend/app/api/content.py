from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import Connection

from app.api.deps import get_cfg, get_conn, require_language
from app.config import AppConfig
from app.engine.evidence import content_evidence
from app.ingest.youtube import YouTubeError, fetch_captions, fetch_info, parse_video_id
from app.jobs import history  # noqa: F401 - registers the job handler
from app.jobs.runner import enqueue, get_job, latest_job
from app.services import content

router = APIRouter(prefix="/api", tags=["content"])


class AddYouTube(BaseModel):
    lang: str = Field(min_length=2, max_length=8)
    url: str = Field(min_length=11, max_length=500)


class HistoryRequest(BaseModel):
    lang: str | None = Field(default=None, max_length=8)
    limit: int | None = Field(default=None, ge=1, le=2000)


@router.get("/content")
def list_content(
    lang: str = Query(..., min_length=2, max_length=8),
    q: str | None = Query(None, max_length=100),
    kind: str | None = Query(None, pattern="^(youtube|local)$"),
    limit: int = Query(60, ge=1, le=300),
    offset: int = Query(0, ge=0),
    conn: Connection = Depends(get_conn),
) -> dict[str, Any]:
    require_language(conn, lang)
    return content.list_items(conn, lang, q=q, kind=kind, limit=limit, offset=offset)


@router.post("/content/youtube", status_code=201)
def add_youtube(body: AddYouTube, conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    require_language(conn, body.lang)
    video_id = parse_video_id(body.url)
    if not video_id:
        raise HTTPException(status_code=422, detail="That doesn't look like a YouTube link.")
    try:
        info = fetch_info(video_id)
    except YouTubeError as exc:
        raise HTTPException(status_code=502, detail=f"YouTube: {exc}") from exc
    item_id = content.upsert_youtube(
        conn, body.lang, video_id, title=info.title, channel=info.channel, duration=info.duration
    )
    content.mark_opened(conn, item_id)
    if not content.cues_of(conn, item_id):
        try:
            captions = fetch_captions(video_id, body.lang, info)
        except YouTubeError:
            captions = None
        if captions:
            content.save_transcript(conn, item_id, body.lang, captions.kind, captions.fmt, captions.cues)
            content.set_metadata(conn, item_id, captions=captions.kind, caption_track=captions.track_lang)
            content.analyze_item(conn, item_id)
        else:
            content.set_metadata(conn, item_id, captions="none")
    return content.get_item(conn, item_id)


@router.post("/content/scan")
def scan(conn: Connection = Depends(get_conn), cfg: AppConfig = Depends(get_cfg)) -> dict[str, Any]:
    return content.scan_media(conn, cfg)


@router.get("/content/evidence")
def evidence(
    lang: str = Query(..., min_length=2, max_length=8), conn: Connection = Depends(get_conn)
) -> dict[str, Any]:
    require_language(conn, lang)
    return {**content_evidence(conn, lang), "job": latest_job(conn, "fetch_history_captions")}


@router.post("/content/history/fetch", status_code=202)
def fetch_history(body: HistoryRequest, conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    job_id = enqueue(conn, "fetch_history_captions", body.model_dump(exclude_none=True))
    return {"job_id": job_id}


@router.get("/jobs/{job_id}")
def job(job_id: int, conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    found = get_job(conn, job_id)
    if not found:
        raise HTTPException(status_code=404, detail="no such job")
    return found


@router.get("/content/{item_id}")
def get_item(item_id: int, conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    try:
        item = content.get_item(conn, item_id)
    except content.ContentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    content.mark_opened(conn, item_id)
    return item


@router.post("/content/{item_id}/captions")
def refetch_captions(item_id: int, conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    try:
        item = content.get_item(conn, item_id)
    except content.ContentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if item["source"] != "youtube":
        raise HTTPException(status_code=422, detail="Captions can only be fetched for YouTube videos.")
    try:
        captions = fetch_captions(item["external_id"], item["language"])
    except YouTubeError as exc:
        raise HTTPException(status_code=502, detail=f"YouTube: {exc}") from exc
    if not captions:
        content.set_metadata(conn, item_id, captions="none")
        raise HTTPException(status_code=404, detail="This video has no captions in this language.")
    content.save_transcript(conn, item_id, item["language"], captions.kind, captions.fmt, captions.cues)
    content.set_metadata(conn, item_id, captions=captions.kind, caption_track=captions.track_lang)
    content.analyze_item(conn, item_id)
    return content.get_item(conn, item_id)


@router.get("/content/{item_id}/transcript")
def transcript(item_id: int, conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    try:
        return content.annotated_transcript(conn, item_id)
    except content.ContentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/content/{item_id}/media")
def media(item_id: int, request: Request, conn: Connection = Depends(get_conn), cfg: AppConfig = Depends(get_cfg)) -> FileResponse:
    try:
        path = content.media_path(cfg, content.get_item(conn, item_id))
    except content.ContentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path)  # Starlette serves HTTP Range requests, so seeking works
