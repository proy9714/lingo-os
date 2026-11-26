"""Downloading a recording (audio or video) to keep on a device for offline listening.

A browser on the computer simply downloads GET /api/content/{id}/media. The phone talks to the laptop or server
through an encrypted channel that carries whole answers, not streams, so it downloads in slices instead:

  GET /api/content/{id}/media/info                    {available, bytes, mime, via}
  GET /api/content/{id}/media/chunk?offset=&length=   up to 2 MB of the file, as bytes

`via` says where the recording comes from: "server" (a file the laptop or server has), "enclosure" (a podcast
episode the device can download straight from the publisher; set by the podcast service) or "none" (YouTube: only
the transcript can be saved).
"""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import Connection

from app.api.deps import get_cfg, get_conn
from app.config import AppConfig
from app.services import content

router = APIRouter(prefix="/api", tags=["offline"])

MAX_CHUNK = 2 * 1024 * 1024


def recording_path(cfg: AppConfig, conn: Connection, item: dict[str, Any], *, fetch: bool = False) -> Path | None:
    """The item's recording on this laptop or server, if there is one (fetch=True may download a podcast episode)."""
    if item["source"] == "local":
        try:
            return content.media_path(cfg, item)
        except content.ContentError:
            return None
    if item["type"] == "podcast_episode":
        try:
            from app.services import podcasts  # noqa: PLC0415 - the podcast service keeps episode audio
        except ImportError:
            return None
        cached = podcasts.local_audio(cfg, conn, item)
        if cached or not fetch:
            return cached
        return podcasts.ensure_local_audio(conn, cfg, item["id"])
    return None


# the same answer on every system (Windows, for one, calls .mp3 "audio/mp3")
MIME = {
    ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".aac": "audio/aac", ".ogg": "audio/ogg", ".opus": "audio/ogg",
    ".wav": "audio/wav", ".flac": "audio/flac", ".mp4": "video/mp4", ".m4v": "video/mp4", ".webm": "video/webm",
    ".mkv": "video/x-matroska", ".mov": "video/quicktime",
}


def _mime(path: Path) -> str:
    return MIME.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def media_info(cfg: AppConfig, conn: Connection, item: dict[str, Any]) -> dict[str, Any]:
    path = recording_path(cfg, conn, item)
    if path:
        return {"available": True, "bytes": path.stat().st_size, "mime": _mime(path), "via": "server"}
    meta = item.get("metadata") or {}
    if item["type"] == "podcast_episode" and meta.get("enclosure_url"):
        return {
            "available": True,
            "bytes": meta.get("enclosure_bytes"),
            "mime": meta.get("enclosure_type") or "audio/mpeg",
            "via": "enclosure",
            "url": meta["enclosure_url"],
        }
    return {"available": False, "via": "none"}


def _item(conn: Connection, item_id: int) -> dict[str, Any]:
    try:
        return content.get_item(conn, item_id)
    except content.ContentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/content/{item_id}/media/info")
def info(item_id: int, conn: Connection = Depends(get_conn), cfg: AppConfig = Depends(get_cfg)) -> dict[str, Any]:
    return media_info(cfg, conn, _item(conn, item_id))


@router.get("/content/{item_id}/media/chunk")
def chunk(
    item_id: int,
    offset: int = Query(ge=0),
    length: int = Query(default=MAX_CHUNK, ge=1, le=MAX_CHUNK),
    conn: Connection = Depends(get_conn),
    cfg: AppConfig = Depends(get_cfg),
) -> Response:
    path = recording_path(cfg, conn, _item(conn, item_id), fetch=True)
    if not path:
        raise HTTPException(status_code=404, detail="there's no recording of this to download")
    total = path.stat().st_size
    if offset > total:
        raise HTTPException(status_code=416, detail="past the end of the file")
    with path.open("rb") as f:
        f.seek(offset)
        data = f.read(length)
    return Response(data, media_type=_mime(path), headers={"X-Total-Bytes": str(total), "X-Offset": str(offset)})
