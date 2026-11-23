"""Immersion sessions: manual logging (automatic tracking arrives with the player in Phase 2)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import Connection, text

from app.sync.ids import new_ulid
from app.timeutil import local_midnight_utc, local_noon_utc, local_today, to_iso, utc_now

MODALITY = {
    "video": "listening",
    "podcast": "listening",
    "audio": "listening",
    "reading": "reading",
    "article": "reading",
    "manga": "reading",
    "tutor": "speaking",
    "shadowing": "speaking",
    "conversation": "speaking",
    "class": "mixed",
    "writing": "writing",
    "other": "mixed",
}
MANUAL_ACTIVITIES = ("video", "podcast", "audio", "reading", "manga", "conversation", "class", "writing", "other")


class ActivityError(ValueError):
    pass


def log_manual(
    conn: Connection,
    *,
    language: str,
    activity: str,
    minutes: int,
    day: date | None = None,
    title: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    if activity not in MANUAL_ACTIVITIES:
        raise ActivityError(f"unknown activity '{activity}'")
    if not 1 <= minutes <= 720:
        raise ActivityError("minutes must be between 1 and 720")
    exists = conn.execute(text("SELECT 1 FROM languages WHERE code = :c AND enabled = 1"), {"c": language}).first()
    if not exists:
        raise ActivityError(f"unknown language '{language}'")

    today = local_today()
    day = day or today
    if day > today:
        raise ActivityError("cannot log time in the future")
    # Today: the session ends now, but never starts before local midnight (logging just after 00:00 still counts
    # for today). Earlier days: centred on local noon so it lands on that day.
    if day == today:
        start = max(utc_now() - timedelta(minutes=minutes), local_midnight_utc(today))
    else:
        start = local_noon_utc(day)
    end = start + timedelta(minutes=minutes)
    client_uuid = new_ulid()

    conn.execute(
        text(
            "INSERT INTO activity_sessions (language_code, activity, modality, tracking, title, started_at, "
            "ended_at, active_seconds, notes, client_uuid) VALUES (:lang, :activity, :modality, 'manual', "
            ":title, :start, :end, :seconds, :notes, :uuid)"
        ),
        {
            "lang": language,
            "activity": activity,
            "modality": MODALITY[activity],
            "title": (title or "").strip() or None,
            "start": to_iso(start),
            "end": to_iso(end),
            "seconds": minutes * 60,
            "notes": (notes or "").strip() or None,
            "uuid": client_uuid,
        },
    )
    return {"client_uuid": client_uuid, "language": language, "activity": activity, "minutes": minutes, "date": day.isoformat()}


def recent_sessions(conn: Connection, language: str, limit: int = 20) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            "SELECT id, activity, modality, tracking, title, started_at, active_seconds FROM activity_sessions "
            "WHERE language_code = :lang AND is_baseline = 0 ORDER BY started_at DESC LIMIT :limit"
        ),
        {"lang": language, "limit": limit},
    ).all()
    return [
        {
            "id": r[0],
            "activity": r[1],
            "modality": r[2],
            "tracking": r[3],
            "title": r[4],
            "started_at": r[5],
            "minutes": round(r[6] / 60),
        }
        for r in rows
    ]
