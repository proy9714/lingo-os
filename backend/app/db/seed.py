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
    from app.config import forget_added_languages
    from app.services import languages

    if not conn.execute(text("SELECT COUNT(*) FROM languages")).scalar():
        for code in cfg.starting_languages:  # a brand-new data folder (tests, or codes listed in config/app.yaml)
            languages.add_row(conn, code, None)
    languages.refresh_details(conn)
    forget_added_languages()
    codes = languages.added_codes(conn)
    if codes:
        settings_store.setdefault(conn, "active_language", cfg.default_language if cfg.default_language in codes else codes[0])
    goals = settings_store.get(conn, "goals", {}) or {}
    missing = {code: cfg.default_goal_minutes for code in codes if code not in goals}
    if missing or not settings_store.get(conn, "goals"):
        settings_store.put(conn, "goals", {**goals, **missing})
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
