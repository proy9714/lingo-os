"""Phone sync, managed from the laptop: turn the Wi-Fi listener on, pair a phone, list or remove phones, offline packs."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import Connection

from app.api.deps import get_cfg, get_conn, get_dict_conn
from app.config import AppConfig
from app.db import settings_store
from app.sync import hub, packs

router = APIRouter(prefix="/api", tags=["devices"])


class EnableRequest(BaseModel):
    enabled: bool
    port: int | None = Field(default=None, ge=1024, le=65535)


class PairRequest(BaseModel):
    name: str = Field(default="Phone", max_length=60)


def phone_sync_allowed() -> bool:
    """LINGO_PHONE_SYNC=off for a test or demo server: it must never take the phone's port or pair a real phone."""
    return os.environ.get("LINGO_PHONE_SYNC", "").lower() not in {"off", "0", "false", "no"}


def _temporary(path: Path) -> bool:
    try:
        return path.resolve().is_relative_to(Path(tempfile.gettempdir()).resolve())
    except OSError:
        return False


def start_listener(app: Any, cfg: AppConfig, port: int) -> None:
    from app.sync.server import create_sync_app

    if not getattr(app.state, "sync_app", None):
        app.state.sync_app = create_sync_app(app, app.state.engine, cfg)
    app.state.sync_listener.start(app.state.sync_app, port)


def _status(request: Request, conn: Connection) -> dict[str, Any]:
    listener = request.app.state.sync_listener
    port = int(settings_store.get(conn, "sync.port", hub.SYNC_PORT))
    data_dir = request.app.state.cfg.data_dir if hasattr(request.app.state, "cfg") else None
    return {
        # which data a phone pairs with: two copies of Lingo OS on one laptop look the same from the phone
        "data_dir": str(data_dir) if data_dir else None,
        "temporary": bool(data_dir and _temporary(Path(data_dir))),
        "allowed": phone_sync_allowed(),
        "enabled": bool(settings_store.get(conn, "sync.enabled", False)),
        "running": listener.running,
        "error": listener.error,
        "port": port,
        "addresses": [f"http://{a}:{port}" for a in hub.lan_addresses()],
        "tailscale": hub.tailscale_addresses(),
        "extra_addresses": hub.extra_addresses(conn),
        "devices": hub.list_devices(conn),
    }


@router.get("/sync/status")
def status(request: Request, conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    return _status(request, conn)


@router.post("/sync/enable")
def enable(body: EnableRequest, request: Request, conn: Connection = Depends(get_conn), cfg: AppConfig = Depends(get_cfg)) -> dict[str, Any]:
    if body.port:
        settings_store.put(conn, "sync.port", body.port)
    if body.enabled and not phone_sync_allowed():
        raise HTTPException(status_code=409, detail="Phone sync is turned off for this server (LINGO_PHONE_SYNC=off).")
    settings_store.put(conn, "sync.enabled", body.enabled)
    listener = request.app.state.sync_listener
    if body.enabled:
        start_listener(request.app, cfg, int(settings_store.get(conn, "sync.port", hub.SYNC_PORT)))
    else:
        listener.stop()
    return _status(request, conn)


class AddressesRequest(BaseModel):
    addresses: list[str] = Field(default_factory=list, max_length=5)


@router.put("/sync/addresses")
def set_addresses(body: AddressesRequest, request: Request, conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    """Addresses for syncing away from home (a Tailscale name, say); phones learn them on their next sync."""
    try:
        hub.set_extra_addresses(conn, body.addresses)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _status(request, conn)


@router.post("/sync/pair")
def pair(body: PairRequest, request: Request, conn: Connection = Depends(get_conn), cfg: AppConfig = Depends(get_cfg)) -> dict[str, Any]:
    if not settings_store.get(conn, "sync.enabled", False):
        raise HTTPException(status_code=409, detail="Turn on phone sync first.")
    return hub.start_pairing(conn, cfg, body.name)


@router.delete("/devices/{device_id}")
def remove(device_id: str, conn: Connection = Depends(get_conn)) -> dict[str, bool]:
    hub.revoke(conn, device_id)
    from app.sync.server import forget_device

    forget_device(device_id)
    return {"removed": True}


@router.get("/packs")
def pack_list(conn: Connection = Depends(get_conn), device: str | None = Header(default=None, alias="X-Lingo-Device")) -> list[dict[str, Any]]:
    if not device:
        raise HTTPException(status_code=400, detail="offline packs are listed for a paired phone")
    return packs.device_packs(conn, device)


@router.get("/packs/{item_id}")
def pack(
    item_id: int,
    conn: Connection = Depends(get_conn),
    dict_conn: Connection = Depends(get_dict_conn),
    device: str | None = Header(default=None, alias="X-Lingo-Device"),
) -> dict[str, Any]:
    try:
        data = packs.build_pack(conn, dict_conn, item_id)
    except packs.PackError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if device:
        packs.register(conn, device, item_id, packs.pack_size(data))
    return data
