"""Key/value preferences in `app_settings` (JSON values)."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import Connection, text

from app.timeutil import to_iso, utc_now


def get(conn: Connection, key: str, default: Any = None) -> Any:
    row = conn.execute(text("SELECT value_json FROM app_settings WHERE key = :k"), {"k": key}).first()
    return json.loads(row[0]) if row else default


def put(conn: Connection, key: str, value: Any) -> None:
    conn.execute(
        text(
            "INSERT INTO app_settings (key, value_json, updated_at) VALUES (:k, :v, :t) "
            "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at"
        ),
        {"k": key, "v": json.dumps(value, ensure_ascii=False), "t": to_iso(utc_now())},
    )


def setdefault(conn: Connection, key: str, value: Any) -> None:
    conn.execute(
        text("INSERT OR IGNORE INTO app_settings (key, value_json) VALUES (:k, :v)"),
        {"k": key, "v": json.dumps(value, ensure_ascii=False)},
    )
