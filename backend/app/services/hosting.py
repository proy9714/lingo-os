"""Where Lingo OS runs for you: on this laptop, or on your cloud server (docs/DEPLOY.md, "Two ways to run").

  local   this laptop is the hub: you use it in a browser here, and your phone pairs with it and syncs with it
          (home Wi-Fi, or Tailscale away from home). This is how every laptop starts.
  cloud   your cloud server is the hub: the laptop's browser and the phone both use the server, so they always show
          the same data. This laptop's own copy steps aside: its pages send you to the server, its phone listener and
          background searches stay off, and the scheduled tasks skip their runs.

The choice is saved in this laptop's database (`hosting`). A server (LINGO_PUBLIC_URL set) is always the hub itself.
Switching doesn't copy any data: deploy/push-data.ps1 copies the laptop's data to the server, deploy/pull-data.ps1
brings the server's data back to the laptop.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any

from sqlalchemy import Connection

from app.config import AppConfig
from app.db import settings_store

KEY = "hosting"
MODES = ("local", "cloud")
CLOUD_URL = re.compile(r"^https?://[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?(?::\d{1,5})?$")


class HostingError(ValueError):
    pass


def role(cfg: AppConfig) -> str:
    """'server' for a Lingo OS that others connect to (docs/DEPLOY.md), 'laptop' otherwise."""
    return "server" if cfg.public_url else "laptop"


def get(conn: Connection, cfg: AppConfig) -> dict[str, Any]:
    saved = settings_store.get(conn, KEY) or {}
    mode = saved.get("mode") if saved.get("mode") in MODES else "local"
    out: dict[str, Any] = {"role": role(cfg), "mode": mode, "cloud_url": saved.get("cloud_url") or None}
    if out["role"] == "server":
        out.update(mode="local", cloud_url=None, public_url=cfg.public_url)  # a server is the hub itself
    return out


def uses_cloud(conn: Connection, cfg: AppConfig) -> bool:
    """This laptop hands everything to the cloud server (no phone listener, no background searches here)."""
    current = get(conn, cfg)
    return current["role"] == "laptop" and current["mode"] == "cloud" and bool(current["cloud_url"])


def clean_url(value: str) -> str:
    url = (value or "").strip().rstrip("/")
    if url and "://" not in url:
        url = f"https://{url}"
    if not CLOUD_URL.match(url):
        raise HostingError(f"'{value}' isn't a server address; use one like https://lingo-os.tail1234.ts.net")
    return url


def check(url: str, timeout: float = 6.0) -> dict[str, Any]:
    """Whether a Lingo OS answers at this address (its /api/health needs no sign-in)."""
    try:
        with urllib.request.urlopen(f"{url}/api/health", timeout=timeout) as response:  # noqa: S310 - the user's own server
            body = json.loads(response.read().decode("utf-8") or "{}")
        return {"reachable": bool(body.get("ok")), "version": body.get("version")}
    except (urllib.error.URLError, OSError, ValueError) as exc:
        reason = getattr(exc, "reason", exc)
        return {"reachable": False, "error": str(reason)[:200]}


def put(conn: Connection, cfg: AppConfig, mode: str, cloud_url: str | None) -> dict[str, Any]:
    if role(cfg) == "server":
        raise HostingError("This is the cloud server itself: laptops and phones connect to it, it doesn't switch.")
    if mode not in MODES:
        raise HostingError(f"mode must be one of {', '.join(MODES)}")
    saved = settings_store.get(conn, KEY) or {}
    url = clean_url(cloud_url) if cloud_url else saved.get("cloud_url")
    if mode == "cloud" and not url:
        raise HostingError("Enter your cloud server's address first.")
    settings_store.put(conn, KEY, {"mode": mode, "cloud_url": url})
    if mode == "cloud":
        # phones pair with the server now; this laptop stops listening for them
        settings_store.put(conn, "sync.enabled", False)
    return get(conn, cfg)
