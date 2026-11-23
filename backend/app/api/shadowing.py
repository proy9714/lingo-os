"""Shadowing studio: clips, recorded attempts and their comparison with the line."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import Connection, text

from app.api.deps import get_cfg, get_conn, require_language
from app.config import AppConfig
from app.services import shadowing

router = APIRouter(prefix="/api/shadow", tags=["shadowing"])

AUDIO_TYPES = {"audio/webm": ".webm", "audio/ogg": ".ogg", "audio/mp4": ".m4a", "audio/mpeg": ".mp3", "audio/wav": ".wav"}


class NewClip(BaseModel):
    lang: str = Field(min_length=2, max_length=8)
    text: str = Field(min_length=1, max_length=500)
    content_item_id: int | None = None
    cue_id: int | None = None
    start_ms: int = Field(default=0, ge=0)
    end_ms: int = Field(default=0, ge=0)


class ClipPatch(BaseModel):
    favorite: bool


def _fail(exc: shadowing.ShadowError, status: int = 404) -> HTTPException:
    return HTTPException(status_code=status, detail=str(exc))


@router.get("/clips")
def clips(lang: str = Query(..., min_length=2, max_length=8), conn: Connection = Depends(get_conn)) -> list[dict[str, Any]]:
    return shadowing.list_clips(conn, lang)


@router.post("/clips", status_code=201)
def create(body: NewClip, conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    require_language(conn, body.lang)
    start_ms, end_ms = body.start_ms, body.end_ms
    if body.cue_id is not None:  # take the timing from the transcript line itself
        cue = conn.execute(
            text(
                "SELECT c.start_ms, c.end_ms, t.content_item_id FROM transcript_cues c JOIN transcripts t ON t.id = c.transcript_id "
                "WHERE c.id = :c"
            ),
            {"c": body.cue_id},
        ).first()
        if not cue:
            raise HTTPException(status_code=404, detail="no such transcript line")
        start_ms, end_ms = cue[0], cue[1]
    try:
        return shadowing.create_clip(
            conn, lang=body.lang, text_value=body.text, content_item_id=body.content_item_id, cue_id=body.cue_id,
            start_ms=start_ms, end_ms=end_ms,
        )
    except shadowing.ShadowError as exc:
        raise _fail(exc, 422) from exc


@router.get("/clips/{clip_id}")
def clip(clip_id: int, conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    try:
        return shadowing.get_clip(conn, clip_id)
    except shadowing.ShadowError as exc:
        raise _fail(exc) from exc


@router.patch("/clips/{clip_id}")
def patch(clip_id: int, body: ClipPatch, conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    shadowing.set_favorite(conn, clip_id, body.favorite)
    return shadowing.get_clip(conn, clip_id)


@router.delete("/clips/{clip_id}")
def delete(clip_id: int, conn: Connection = Depends(get_conn), cfg: AppConfig = Depends(get_cfg)) -> dict[str, bool]:
    try:
        shadowing.delete_clip(conn, cfg, clip_id)
    except shadowing.ShadowError as exc:
        raise _fail(exc) from exc
    return {"deleted": True}


@router.post("/clips/{clip_id}/attempts", status_code=201)
async def attempt(
    clip_id: int,
    audio: UploadFile = File(...),
    duration_ms: int = Form(0, ge=0),
    heard: str = Form("", max_length=1000),
    conn: Connection = Depends(get_conn),
    cfg: AppConfig = Depends(get_cfg),
) -> dict[str, Any]:
    data = await audio.read(shadowing.MAX_RECORDING + 1)
    content_type = (audio.content_type or "audio/webm").split(";")[0]
    suffix = AUDIO_TYPES.get(content_type)
    if suffix is None:
        raise HTTPException(status_code=422, detail="unsupported audio format")
    try:
        return shadowing.add_attempt(conn, cfg, clip_id, audio=data, suffix=suffix, duration_ms=duration_ms, heard=heard)
    except shadowing.ShadowError as exc:
        raise _fail(exc, 422) from exc


@router.get("/attempts/{attempt_id}/audio")
def recording(attempt_id: int, conn: Connection = Depends(get_conn), cfg: AppConfig = Depends(get_cfg)) -> FileResponse:
    try:
        return FileResponse(shadowing.recording_path(cfg, conn, attempt_id))
    except shadowing.ShadowError as exc:
        raise _fail(exc) from exc
