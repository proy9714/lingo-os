"""Idempotent startup data: languages from config, default preferences, this laptop's device row."""

from __future__ import annotations

import json
import platform
from pathlib import Path

from sqlalchemy import Connection, text

from app.config import AppConfig
from app.db import settings_store
from app.sync.ids import new_ulid


def seed(conn: Connection, cfg: AppConfig) -> None:
    for lang in cfg.languages:
        conn.execute(
            text(
                "INSERT INTO languages (code, name, native_name, accent_color, writing_mode, enabled) "
                "VALUES (:code, :name, :native, :accent, :mode, 1) "
                "ON CONFLICT(code) DO UPDATE SET name = excluded.name, native_name = excluded.native_name, "
                "accent_color = excluded.accent_color, writing_mode = excluded.writing_mode"
            ),
            {
                "code": lang.code,
                "name": lang.name,
                "native": lang.native_name,
                "accent": lang.accent,
                "mode": lang.writing_mode,
            },
        )
    settings_store.setdefault(conn, "active_language", cfg.default_language)
    settings_store.setdefault(conn, "goals", {lang.code: cfg.default_goal_minutes for lang in cfg.languages})
    ensure_hub_device(conn, cfg.data_dir)


def hub_device_id(data_dir: Path) -> str:
    """Stable id for this laptop, kept in data/device.json so it survives DB rebuilds."""
    path = data_dir / "device.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))["id"]
    data_dir.mkdir(parents=True, exist_ok=True)
    device_id = new_ulid()
    path.write_text(json.dumps({"id": device_id, "kind": "hub"}, indent=2), encoding="utf-8")
    return device_id


def ensure_hub_device(conn: Connection, data_dir: Path) -> str:
    device_id = hub_device_id(data_dir)
    conn.execute(
        text("INSERT OR IGNORE INTO devices (id, name, kind) VALUES (:id, :name, 'hub')"),
        {"id": device_id, "name": platform.node() or "Laptop"},
    )
    return device_id
