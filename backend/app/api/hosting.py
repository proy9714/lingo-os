"""Settings → Where Lingo OS runs: this laptop, or your cloud server (app/services/hosting.py)."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import Connection

from app.api.deps import get_cfg, get_conn
from app.config import AppConfig
from app.services import hosting

router = APIRouter(prefix="/api", tags=["hosting"])


class HostingRequest(BaseModel):
    mode: Literal["local", "cloud"]
    cloud_url: str | None = Field(default=None, max_length=300)


@router.get("/hosting")
def get_hosting(conn: Connection = Depends(get_conn), cfg: AppConfig = Depends(get_cfg)) -> dict[str, Any]:
    return hosting.get(conn, cfg)


@router.put("/hosting")
def set_hosting(
    body: HostingRequest, request: Request, conn: Connection = Depends(get_conn), cfg: AppConfig = Depends(get_cfg)
) -> dict[str, Any]:
    try:
        result = hosting.put(conn, cfg, body.mode, body.cloud_url)
    except hosting.HostingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if result["mode"] == "cloud":
        request.app.state.sync_listener.stop()
    return result


@router.post("/hosting/check")
def check_server(body: HostingRequest) -> dict[str, Any]:
    """Does a Lingo OS answer at this address? (from this laptop, so over Tailscale if that's how it's reached)"""
    try:
        url = hosting.clean_url(body.cloud_url or "")
    except hosting.HostingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"url": url, **hosting.check(url)}
