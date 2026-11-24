from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import Connection

from app.api.deps import get_cfg, get_conn
from app.config import AppConfig
from app.engine.profile import sync_baselines
from app.ingest import immersion_tracker as tracker

router = APIRouter(prefix="/api/imports", tags=["imports"])


class TrackerImport(BaseModel):
    path: str | None = None


@router.post("/tracker")
def import_tracker(
    body: TrackerImport | None = None, conn: Connection = Depends(get_conn), cfg: AppConfig = Depends(get_cfg)
) -> dict[str, Any]:
    folder = Path(body.path) if body and body.path else cfg.tracker_path
    if folder is None:
        raise HTTPException(status_code=422, detail="No Immersion Tracker folder configured (immersion_tracker.path in config/app.local.yaml)")
    try:
        summary = tracker.import_tracker_folder(conn, cfg.data_dir, folder, cfg.language_codes)
        sync_baselines(conn, cfg)  # new hours can move an untested starting estimate
        return summary
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except tracker.NotATrackerFile as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/tracker/flags")
def flags(conn: Connection = Depends(get_conn)) -> list[dict[str, Any]]:
    return tracker.pending_flags(conn)


@router.post("/tracker/flags/{entry_id}/count")
def count_flag(entry_id: str, conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    if not tracker.confirm_duplicate(conn, entry_id):
        raise HTTPException(status_code=404, detail="no such flagged entry")
    return {"counted": entry_id}
