from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app import __version__
from app.api.deps import get_cfg
from app.config import AppConfig
from app.services.doctor import run_checks

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "version": __version__}


@router.get("/system/status")
def system_status(cfg: AppConfig = Depends(get_cfg)) -> dict[str, Any]:
    return run_checks(cfg)
