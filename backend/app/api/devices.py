"""Phone sync, managed from the laptop: turn the Wi-Fi listener on, pair a phone, list or remove phones, offline packs."""

from __future__ import annotations

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


def start_listener(app: Any, cfg: AppConfig, port: int) -> None:
    from app.sync.server import create_sync_app

    if not getattr(app.state, "sync_app", None):
        app.state.sync_app = create_sync_app(app, app.state.engine, cfg)
    app.state.sync_listener.start(app.state.sync_app, port)


def _status(request: Request, conn: Connection) -> dict[str, Any]:
    listener = request.app.state.sync_listener
    port = int(settings_store.get(conn, "sync.port", hub.SYNC_PORT))
    return {
        "enabled": bool(settings_store.get(conn, "sync.enabled", False)),
        "running": listener.running,
        "error": listener.error,
        "port": port,
        "addresses": [f"http://{a}:{port}" for a in hub.lan_addresses()],
        "devices": hub.list_devices(conn),
    }


@router.get("/sync/status")
def status(request: Request, conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    return _status(request, conn)


@router.post("/sync/enable")
def enable(body: EnableRequest, request: Request, conn: Connection = Depends(get_conn), cfg: AppConfig = Depends(get_cfg)) -> dict[str, Any]:
    if body.port:
        settings_store.put(conn, "sync.port", body.port)
    settings_store.put(conn, "sync.enabled", body.enabled)
    listener = request.app.state.sync_listener
    if body.enabled:
        start_listener(request.app, cfg, int(settings_store.get(conn, "sync.port", hub.SYNC_PORT)))
    else:
        listener.stop()
    return _status(request, conn)


@router.post("/sync/pair")
def pair(body: PairRequest, request: Request, conn: Connection = Depends(get_conn), cfg: AppConfig = Depends(get_cfg)) -> dict[str, Any]:
    if not settings_store.get(conn, "sync.enabled", False):
        raise HTTPException(status_code=409, detail="Turn on phone sync first.")
    return hub.start_pairing(conn, cfg, body.name)


@router.delete("/devices/{device_id}")
def remove(device_id: str, conn: Connection = Depends(get_conn)) -> dict[str, bool]:
    hub.revoke(conn, device_id)
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
