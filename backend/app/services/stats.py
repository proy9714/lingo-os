"""Immersion statistics. Days and months follow the laptop's local calendar."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from sqlalchemy import Connection, text

from app.config import AppConfig
from app.db import settings_store
from app.services.estimate import hours_estimate
from app.timeutil import hours, local_day, local_midnight_utc, local_month, local_today, minutes, to_iso


def goal_minutes(conn: Connection, cfg: AppConfig, language: str) -> int:
    goals = settings_store.get(conn, "goals", {}) or {}
    return int(goals.get(language, cfg.default_goal_minutes))


def today_stats(conn: Connection, cfg: AppConfig, language: str, today: date | None = None) -> dict[str, Any]:
    today = today or local_today()
    first_day = today - timedelta(days=6)
    rows = conn.execute(
        text(
            "SELECT started_at, active_seconds FROM activity_sessions "
            "WHERE language_code = :lang AND is_baseline = 0 AND started_at >= :since"
        ),
        {"lang": language, "since": to_iso(local_midnight_utc(first_day) - timedelta(days=1))},
    ).all()
    per_day: dict[date, int] = {first_day + timedelta(days=i): 0 for i in range(7)}
    for started_at, seconds in rows:
        day = local_day(started_at)
        if day in per_day:
            per_day[day] += seconds

    last = conn.execute(
        text(
            "SELECT started_at, active_seconds, title FROM activity_sessions "
            "WHERE language_code = :lang AND is_baseline = 0 ORDER BY started_at DESC LIMIT 1"
        ),
        {"lang": language},
    ).first()
    last_day_minutes = 0
    if last:
        last_day = local_day(last[0])
        last_day_minutes = minutes(
            sum(
                secs
                for started, secs in conn.execute(
                    text(
                        "SELECT started_at, active_seconds FROM activity_sessions "
                        "WHERE language_code = :lang AND is_baseline = 0 AND started_at >= :since"
                    ),
                    {"lang": language, "since": to_iso(local_midnight_utc(last_day) - timedelta(days=1))},
                ).all()
                if local_day(started) == last_day
            )
        )

    return {
        "language": language,
        "date": today.isoformat(),
        "today_minutes": minutes(per_day[today]),
        "goal_minutes": goal_minutes(conn, cfg, language),
        "last7": [{"date": day.isoformat(), "minutes": minutes(secs)} for day, secs in per_day.items()],
        "last_session": (
            {
                "date": local_day(last[0]).isoformat(),
                "title": last[2],
                "minutes": minutes(last[1]),
                "day_minutes": last_day_minutes,
            }
            if last
            else None
        ),
    }


def language_overview(conn: Connection, cfg: AppConfig, language: str) -> dict[str, Any]:
    totals = conn.execute(
        text(
            "SELECT COALESCE(SUM(active_seconds), 0), "
            "COALESCE(SUM(CASE WHEN is_baseline = 1 THEN active_seconds END), 0), "
            "COALESCE(SUM(CASE WHEN is_baseline = 0 THEN 1 END), 0), "
            "COUNT(DISTINCT content_item_id) "
            "FROM activity_sessions WHERE language_code = :lang"
        ),
        {"lang": language},
    ).one()
    total_s, baseline_s, sessions, items = totals

    rows = conn.execute(
        text(
            "SELECT started_at, active_seconds, modality FROM activity_sessions "
            "WHERE language_code = :lang AND is_baseline = 0 ORDER BY started_at"
        ),
        {"lang": language},
    ).all()
    monthly: dict[str, int] = defaultdict(int)
    by_modality: dict[str, int] = defaultdict(int)
    active_days: set[date] = set()
    for started_at, seconds, modality in rows:
        monthly[local_month(started_at)] += seconds
        by_modality[modality] += seconds
        active_days.add(local_day(started_at))

    total_hours = hours(total_s)
    return {
        "language": language,
        "total_hours": total_hours,
        "baseline_hours": hours(baseline_s),
        "tracked_hours": hours(total_s - baseline_s),
        "sessions": sessions,
        "content_items": items,
        "active_days": len(active_days),
        "first_session_date": local_day(rows[0][0]).isoformat() if rows else None,
        "last_session_date": local_day(rows[-1][0]).isoformat() if rows else None,
        "monthly": [{"month": month, "hours": hours(secs)} for month, secs in sorted(monthly.items())],
        "by_modality_hours": {key: hours(secs) for key, secs in sorted(by_modality.items())},
        "estimate": hours_estimate(language, total_s / 3600, cfg.baselines),
    }


def overview(conn: Connection, cfg: AppConfig) -> dict[str, Any]:
    return {"languages": [language_overview(conn, cfg, code) for code in cfg.language_codes]}
