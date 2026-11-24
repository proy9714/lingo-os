"""Phase 8: content discovery, content sources, the weekly review and its reports."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import Connection

from app.api.deps import get_cfg, get_conn, require_language
from app.config import AppConfig
from app.jobs import discovery  # noqa: F401 - registers the jobs
from app.jobs.runner import enqueue, latest_job
from app.services import discover, evolve, topup

router = APIRouter(prefix="/api", tags=["automation"])


class DiscoverRequest(BaseModel):
    lang: str | None = Field(default=None, max_length=8)
    per_run: int | None = Field(default=None, ge=1, le=40)


class EvolveRequest(BaseModel):
    days: int = Field(default=7, ge=1, le=31)
    no_llm: bool = False


class SourcePatch(BaseModel):
    enabled: bool


class TopUpRequest(BaseModel):
    lang: str = Field(min_length=2, max_length=8)
    force: bool = False


class AutoSetting(BaseModel):
    enabled: bool


@router.post("/discover/run", status_code=202)
def run_discovery(body: DiscoverRequest, conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    return {"job_id": enqueue(conn, "update_content", body.model_dump(exclude_none=True))}


@router.get("/discover/status")
def discovery_status(conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    return {"job": latest_job(conn, "update_content"), "runs": discover.recent_runs(conn)}


@router.get("/discover/pool")
def discovery_pool(lang: str = Query(..., min_length=2, max_length=8), conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    """How many suggestions each shelf has, and whether a background search is running or due."""
    require_language(conn, lang)
    return topup.status(conn, lang)


@router.post("/discover/top-up")
def discovery_top_up(body: TopUpRequest, conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    """Start a background search if a shelf is running low (or right away with `force`)."""
    require_language(conn, body.lang)
    return topup.maybe_top_up(conn, body.lang, force=body.force)


@router.put("/discover/auto")
def discovery_auto(body: AutoSetting, conn: Connection = Depends(get_conn)) -> dict[str, bool]:
    from app.db import settings_store

    settings_store.put(conn, "discover.auto", body.enabled)
    return {"enabled": body.enabled}


@router.get("/sources")
def sources(lang: str = Query(..., min_length=2, max_length=8), conn: Connection = Depends(get_conn)) -> list[dict[str, Any]]:
    require_language(conn, lang)
    return discover.list_sources(conn, lang)


@router.patch("/sources/{source_id}")
def patch_source(source_id: int, body: SourcePatch, conn: Connection = Depends(get_conn)) -> dict[str, bool]:
    discover.set_source_enabled(conn, source_id, body.enabled)
    return {"enabled": body.enabled}


@router.post("/evolve/run", status_code=202)
def run_evolve(body: EvolveRequest, conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    return {"job_id": enqueue(conn, "evolve_profile", body.model_dump())}


@router.get("/evolve/status")
def evolve_status(conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    return {"job": latest_job(conn, "evolve_profile")}


@router.get("/reports")
def report_list(conn: Connection = Depends(get_conn)) -> list[dict[str, Any]]:
    return evolve.reports(conn)


@router.get("/reports/file", response_class=PlainTextResponse)
def report_file(path: str = Query(..., max_length=200), cfg: AppConfig = Depends(get_cfg)) -> str:
    root = (cfg.data_dir / "reports").resolve()
    target = (cfg.data_dir / path).resolve()
    if not target.is_relative_to(root) or target.suffix != ".md" or not target.is_file():
        raise HTTPException(status_code=404, detail="no such report")
    return target.read_text(encoding="utf-8")
