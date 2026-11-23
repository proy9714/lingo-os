from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Connection

from app.api.deps import get_cfg, get_conn, require_language
from app.config import AppConfig
from app.services import activity, stats

router = APIRouter(prefix="/api", tags=["stats"])


@router.get("/stats/today")
def today(
    lang: str = Query(..., min_length=2, max_length=8),
    conn: Connection = Depends(get_conn),
    cfg: AppConfig = Depends(get_cfg),
) -> dict[str, Any]:
    require_language(conn, lang)
    return stats.today_stats(conn, cfg, lang)


@router.get("/stats/overview")
def overview(conn: Connection = Depends(get_conn), cfg: AppConfig = Depends(get_cfg)) -> dict[str, Any]:
    return stats.overview(conn, cfg)


@router.get("/activity/recent")
def recent(
    lang: str = Query(..., min_length=2, max_length=8),
    limit: int = Query(20, ge=1, le=200),
    conn: Connection = Depends(get_conn),
) -> list[dict[str, Any]]:
    require_language(conn, lang)
    return activity.recent_sessions(conn, lang, limit)
