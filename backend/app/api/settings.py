from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Connection, text

from app.api.deps import get_cfg, get_conn
from app.config import AppConfig
from app.db import settings_store

router = APIRouter(prefix="/api", tags=["settings"])


class SettingsPatch(BaseModel):
    active_language: str | None = None
    goals: dict[str, int] | None = Field(default=None, description="Daily goal in minutes per language")


def _languages(conn: Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        text("SELECT code, name, native_name, accent_color, writing_mode, enabled FROM languages ORDER BY rowid")
    ).all()
    return [
        {
            "code": r[0],
            "name": r[1],
            "native_name": r[2],
            "accent_color": r[3],
            "writing_mode": r[4],
            "enabled": bool(r[5]),
        }
        for r in rows
    ]


def _settings(conn: Connection, cfg: AppConfig) -> dict[str, Any]:
    goals = settings_store.get(conn, "goals", {}) or {}
    return {
        "active_language": settings_store.get(conn, "active_language", cfg.default_language),
        "goals": {code: int(goals.get(code, cfg.default_goal_minutes)) for code in cfg.language_codes},
        "tracker_path": str(cfg.tracker_path) if cfg.tracker_path else None,
    }


@router.get("/languages")
def list_languages(conn: Connection = Depends(get_conn)) -> list[dict[str, Any]]:
    return _languages(conn)


@router.get("/settings")
def get_settings(conn: Connection = Depends(get_conn), cfg: AppConfig = Depends(get_cfg)) -> dict[str, Any]:
    return _settings(conn, cfg)


@router.patch("/settings")
def patch_settings(
    patch: SettingsPatch, conn: Connection = Depends(get_conn), cfg: AppConfig = Depends(get_cfg)
) -> dict[str, Any]:
    codes = set(cfg.language_codes)
    if patch.active_language is not None:
        if patch.active_language not in codes:
            raise HTTPException(status_code=422, detail=f"unknown language '{patch.active_language}'")
        settings_store.put(conn, "active_language", patch.active_language)
    if patch.goals is not None:
        unknown = set(patch.goals) - codes
        if unknown:
            raise HTTPException(status_code=422, detail=f"unknown languages: {sorted(unknown)}")
        if any(not 1 <= minutes <= 720 for minutes in patch.goals.values()):
            raise HTTPException(status_code=422, detail="daily goals must be between 1 and 720 minutes")
        goals = dict(settings_store.get(conn, "goals", {}) or {})
        goals.update(patch.goals)
        settings_store.put(conn, "goals", goals)
        settings_store.put(conn, "goals_user_edited", True)
    return _settings(conn, cfg)
