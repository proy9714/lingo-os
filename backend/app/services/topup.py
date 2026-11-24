"""Keep suggestions topped up: when a shelf runs low, look for more in the background.

The pages that show suggestions (Today, Watch, Read) ask for a top-up when they open and when you scroll to the end.
A search is queued only when a shelf has fewer suggestions than its target, no search is already running, and the last
one for that language is old enough (longer after YouTube refused). Turn it off with the setting `discover.auto`.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from sqlalchemy import Connection, text

from app.db import settings_store
from app.jobs.runner import enqueue, latest_job
from app.services.recommend import pool_size
from app.timeutil import from_iso, to_iso, utc_now

POOL_TARGET = {"watch": 24, "read": 12}
COOLDOWN = timedelta(hours=2)
COOLDOWN_AFTER_REFUSAL = timedelta(hours=12)


def auto_enabled(conn: Connection) -> bool:
    return bool(settings_store.get(conn, "discover.auto", True))


def _last_run(conn: Connection, lang: str) -> tuple[str | None, bool]:
    """When the last search for this language started (automatic or not), and whether YouTube refused it."""
    row = conn.execute(
        text("SELECT started_at, stats_json FROM scrape_runs WHERE language_code = :l ORDER BY id DESC LIMIT 1"), {"l": lang}
    ).first()
    auto = settings_store.get(conn, f"discover.auto_last.{lang}")
    started = max(filter(None, [row[0] if row else None, auto]), default=None)
    refused = bool(row and json.loads(row[1] or "{}").get("stopped_early"))
    return started, refused


def status(conn: Connection, lang: str) -> dict[str, Any]:
    pools = {shelf: pool_size(conn, lang, shelf) for shelf in POOL_TARGET}
    job = latest_job(conn, "update_content")
    started, refused = _last_run(conn, lang)
    wait = COOLDOWN_AFTER_REFUSAL if refused else COOLDOWN
    next_at = to_iso(from_iso(started) + wait) if started else None
    return {
        "language": lang,
        "auto": auto_enabled(conn),
        "pools": pools,
        "targets": POOL_TARGET,
        "low": [shelf for shelf, target in POOL_TARGET.items() if pools[shelf] < target],
        "searching": bool(job and job["status"] in ("queued", "running")),
        "job": job,
        "last_search_at": started,
        "youtube_refused": refused,
        "next_auto_at": next_at,
    }


def maybe_top_up(conn: Connection, lang: str, *, force: bool = False) -> dict[str, Any]:
    """Queue a background search for the shelves that are running low. `force` skips the cooldown (a button press)."""
    state = status(conn, lang)
    if state["searching"]:
        return {**state, "queued": False, "reason": "already searching"}
    if not force and not state["auto"]:
        return {**state, "queued": False, "reason": "automatic search is off"}
    shelves = state["low"] if not force else list(POOL_TARGET)
    if not shelves:
        return {**state, "queued": False, "reason": "enough suggestions"}
    if not force and state["next_auto_at"] and utc_now() < from_iso(state["next_auto_at"]):
        return {**state, "queued": False, "reason": "searched recently"}
    settings_store.put(conn, f"discover.auto_last.{lang}", to_iso(utc_now()))
    job_id = enqueue(
        conn, "update_content", {"lang": lang, "auto": not force, "videos": "watch" in shelves, "articles": "read" in shelves}
    )
    return {**status(conn, lang), "queued": True, "job_id": job_id, "shelves": shelves}
