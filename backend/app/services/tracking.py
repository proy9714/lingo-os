"""Automatic time tracking: the player (and later the reader) sends a heartbeat every ~15 s while active.

The client counts the seconds it was actually active since its last heartbeat (video playing and
tab visible); the server adds them to an open session, capped so a stuck tab can't inflate totals.
A session that hears nothing for two minutes is closed; the next heartbeat starts a new one.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import Connection, text

from app.services.activity import MODALITY
from app.services.content import record_progress
from app.timeutil import from_iso, to_iso, utc_now

MAX_CREDIT = 30  # seconds credited per heartbeat at most
IDLE_CLOSE = timedelta(minutes=2)
TRACKED_ACTIVITIES = ("video", "podcast", "audio", "reading", "article", "manga", "tutor", "shadowing")


class TrackingError(ValueError):
    pass


def sweep(conn: Connection) -> int:
    """Close sessions that stopped sending heartbeats; drop ones shorter than 10 s (accidental opens)."""
    cutoff = to_iso(utc_now() - IDLE_CLOSE)
    closed = conn.execute(
        text("UPDATE activity_sessions SET is_open = 0 WHERE is_open = 1 AND last_heartbeat_at < :cutoff"), {"cutoff": cutoff}
    ).rowcount
    conn.execute(text("DELETE FROM activity_sessions WHERE tracking = 'auto' AND is_open = 0 AND active_seconds < 10"))
    return closed


def heartbeat(
    conn: Connection,
    *,
    lang: str,
    activity: str,
    session: str,
    seconds: int,
    content_item_id: int | None = None,
    position_ms: int | None = None,
    duration_ms: int | None = None,
) -> dict[str, Any]:
    if activity not in TRACKED_ACTIVITIES:
        raise TrackingError(f"activity '{activity}' is not tracked automatically")
    credit = max(0, min(int(seconds), MAX_CREDIT))
    now = utc_now()
    sweep(conn)
    row = conn.execute(
        text(
            "SELECT id, last_heartbeat_at, active_seconds FROM activity_sessions "
            "WHERE client_uuid LIKE :prefix AND is_open = 1 ORDER BY id DESC LIMIT 1"
        ),
        {"prefix": f"{session}%"},
    ).first()
    if row and now - from_iso(row[1]) <= IDLE_CLOSE:
        session_id = row[0]
        conn.execute(
            text(
                "UPDATE activity_sessions SET active_seconds = active_seconds + :c, last_heartbeat_at = :now, "
                "ended_at = :now WHERE id = :id"
            ),
            {"c": credit, "now": to_iso(now), "id": session_id},
        )
        total = row[2] + credit
    else:
        if row:
            conn.execute(text("UPDATE activity_sessions SET is_open = 0 WHERE id = :id"), {"id": row[0]})
        count = conn.execute(
            text("SELECT COUNT(*) FROM activity_sessions WHERE client_uuid LIKE :prefix"), {"prefix": f"{session}%"}
        ).scalar_one()
        session_id = conn.execute(
            text(
                "INSERT INTO activity_sessions (language_code, activity, modality, tracking, content_item_id, started_at, "
                "ended_at, last_heartbeat_at, active_seconds, is_open, client_uuid) VALUES (:l, :a, :m, 'auto', :item, "
                ":start, :now, :now, :c, 1, :uuid)"
            ),
            {
                "l": lang, "a": activity, "m": MODALITY.get(activity, "mixed"), "item": content_item_id,
                "start": to_iso(now - timedelta(seconds=credit)), "now": to_iso(now), "c": credit,
                "uuid": session if count == 0 else f"{session}:{count}",
            },
        ).lastrowid
        total = credit
    if content_item_id is not None:
        record_progress(conn, content_item_id, position_ms, duration_ms)
    return {"session_id": session_id, "active_seconds": total}


def stop(conn: Connection, session: str) -> None:
    conn.execute(
        text("UPDATE activity_sessions SET is_open = 0 WHERE client_uuid LIKE :prefix AND is_open = 1"),
        {"prefix": f"{session}%"},
    )
