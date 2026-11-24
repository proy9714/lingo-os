"""The laptop as sync hub: its secret, its Wi-Fi address, pairing phones, and checking who is calling."""

from __future__ import annotations

import hmac
import json
import os
import socket
from datetime import timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, text

from app.config import AppConfig
from app.db import settings_store
from app.db.seed import hub_device_id
from app.sync.crypto import b64e, derive_key, hash_token
from app.sync.ids import new_ulid
from app.timeutil import from_iso, to_iso, utc_now

SYNC_PORT = 8788
PAIRING_VALID = timedelta(minutes=10)


class SyncAuthError(Exception):
    pass


def hub_secret(data_dir: Path) -> bytes:
    """32 random bytes kept in data/device.json next to the hub's id (created on first use)."""
    hub_device_id(data_dir)
    path = data_dir / "device.json"
    info = json.loads(path.read_text(encoding="utf-8"))
    if "secret" not in info:
        info["secret"] = b64e(os.urandom(32))
        path.write_text(json.dumps(info, indent=2), encoding="utf-8")
    from app.sync.crypto import b64d

    return b64d(info["secret"])


def lan_addresses() -> list[str]:
    """This laptop's address on the local network (no packet is sent to find it)."""
    found: list[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 80))  # TEST-NET address: picks the outgoing interface only
            found.append(probe.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = info[4][0]
            if address not in found and not address.startswith("127."):
                found.append(address)
    except OSError:
        pass
    private = [a for a in found if a.startswith(("192.168.", "10.")) or a.startswith("172.")]
    return private or found


def start_pairing(conn: Connection, cfg: AppConfig, name: str = "Phone") -> dict[str, Any]:
    """A one-time offer for the QR code: valid for ten minutes, used once."""
    device_id = new_ulid()
    token = b64e(os.urandom(24))
    expires = utc_now() + PAIRING_VALID
    settings_store.put(conn, f"sync.pending.{device_id}", {"token_hash": hash_token(token), "expires": to_iso(expires), "name": name})
    key = derive_key(hub_secret(cfg.data_dir), device_id)
    addresses = lan_addresses()
    port = int(settings_store.get(conn, "sync.port", SYNC_PORT))
    payload = {
        "v": 1,
        "hub": [f"http://{a}:{port}" for a in addresses] or [f"http://127.0.0.1:{port}"],
        "device": device_id,
        "token": token,
        "key": b64e(key),
        "name": conn.execute(text("SELECT name FROM devices WHERE kind = 'hub'")).scalar() or "Laptop",
    }
    return {"device_id": device_id, "expires": to_iso(expires), "qr": json.dumps(payload, separators=(",", ":")), "addresses": addresses}


def confirm_pairing(conn: Connection, device_id: str, token: str, name: str) -> dict[str, Any]:
    key = f"sync.pending.{device_id}"
    pending = settings_store.get(conn, key)
    if not pending:
        raise SyncAuthError("this pairing code is unknown or was already used")
    if from_iso(pending["expires"]) < utc_now():
        conn.execute(text("DELETE FROM app_settings WHERE key = :k"), {"k": key})
        raise SyncAuthError("this pairing code expired; show a new one on the laptop")
    if not hmac.compare_digest(pending["token_hash"], hash_token(token)):
        raise SyncAuthError("wrong pairing token")
    conn.execute(
        text("INSERT INTO devices (id, name, kind, token_hash, last_seen_at) VALUES (:id, :n, 'android', :t, :now)"),
        {"id": device_id, "n": (name or pending.get("name") or "Phone")[:60], "t": pending["token_hash"], "now": to_iso(utc_now())},
    )
    conn.execute(text("DELETE FROM app_settings WHERE key = :k"), {"k": key})
    return {"device_id": device_id, "paired": True}


def pending_key(conn: Connection, cfg: AppConfig, device_id: str) -> bytes | None:
    if settings_store.get(conn, f"sync.pending.{device_id}") is None:
        return None
    return derive_key(hub_secret(cfg.data_dir), device_id)


def device_key(conn: Connection, cfg: AppConfig, device_id: str) -> bytes:
    row = conn.execute(
        text("SELECT revoked_at FROM devices WHERE id = :id AND kind = 'android'"), {"id": device_id}
    ).first()
    if not row or row[0]:
        raise SyncAuthError("this phone isn't paired (or was removed); pair it again")
    return derive_key(hub_secret(cfg.data_dir), device_id)


def authenticate(conn: Connection, device_id: str, token: str) -> None:
    stored = conn.execute(
        text("SELECT token_hash FROM devices WHERE id = :id AND kind = 'android' AND revoked_at IS NULL"), {"id": device_id}
    ).scalar()
    if not stored or not hmac.compare_digest(stored, hash_token(token or "")):
        raise SyncAuthError("this phone isn't paired (or was removed); pair it again")
    conn.execute(text("UPDATE devices SET last_seen_at = :now WHERE id = :id"), {"now": to_iso(utc_now()), "id": device_id})


def list_devices(conn: Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            "SELECT d.id, d.name, d.kind, d.last_seen_at, d.paired_at, d.revoked_at, "
            "(SELECT COUNT(*) FROM sync_log s WHERE s.device_id = d.id), "
            "(SELECT COUNT(*) FROM offline_packs p WHERE p.device_id = d.id AND p.status = 'ready') "
            "FROM devices d ORDER BY d.kind DESC, d.paired_at"
        )
    ).all()
    keys = ("id", "name", "kind", "last_seen_at", "paired_at", "revoked_at", "events", "packs")
    return [dict(zip(keys, r)) for r in rows]


def revoke(conn: Connection, device_id: str) -> None:
    conn.execute(
        text("UPDATE devices SET revoked_at = :now WHERE id = :id AND kind = 'android'"), {"now": to_iso(utc_now()), "id": device_id}
    )
