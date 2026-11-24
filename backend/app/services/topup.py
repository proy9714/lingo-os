"""Keep suggestions topped up: when a shelf runs low, or you scroll to its end, look for more in the background.

The pages that show suggestions (Today, Watch, Read) ask for a top-up when they open and when you reach the end of a
list. Two kinds of background work:
  update_content     list channels and searches (videos), read feeds (articles). Queued for the shelves that are low
                     (under POOL_TARGET) or that you scrolled to the end of; videos at most every 45 minutes, articles
                     every 30 (10 when you're at the end), and no YouTube for a while after it refused (1 hour, doubling up to 12).
  verify_candidates  measure the best-ranked videos whose level is only estimated (captions + word analysis).
Turn it off with the setting `discover.auto`.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import Connection, text

from app.db import settings_store
from app.jobs.runner import enqueue, latest_job
from app.services import catalog
from app.services.recommend import ranked
from app.timeutil import from_iso, to_iso, utc_now

POOL_TARGET = {"watch": 150, "read": 40}
COOLDOWN = {"watch": timedelta(minutes=45), "read": timedelta(minutes=30)}
AT_END_COOLDOWN = timedelta(minutes=10)
VERIFY_COOLDOWN = timedelta(minutes=10)
VERIFY_TOP = 40  # estimated videos among the top this many get measured first
JOB_KINDS = ("update_content", "verify_candidates")


def auto_enabled(conn: Connection) -> bool:
    return bool(settings_store.get(conn, "discover.auto", True))


def _running(conn: Connection) -> dict[str, Any] | None:
    for kind in JOB_KINDS:
        job = latest_job(conn, kind)
        if job and job["status"] in ("queued", "running"):
            return job
    return None


def _last(conn: Connection, lang: str, shelf: str) -> str | None:
    return settings_store.get(conn, f"discover.auto_last.{lang}.{shelf}")


def _last_search(conn: Connection, lang: str) -> str | None:
    row = conn.execute(
        text("SELECT started_at FROM scrape_runs WHERE language_code = :l ORDER BY id DESC LIMIT 1"), {"l": lang}
    ).first()
    return row[0] if row else None


def status(conn: Connection, lang: str) -> dict[str, Any]:
    from app.services.recommend import in_band

    # only content near your level counts: the closest-match fill-ins mean "keep looking"
    pools = {shelf: sum(1 for i in ranked(conn, lang, shelf) if in_band(i)) for shelf in POOL_TARGET}
    estimated = sum(1 for i in ranked(conn, lang, "watch") if i["estimated"])
    job = _running(conn) or latest_job(conn, "update_content")
    refused = catalog.youtube_refused_recently(conn)
    last = _last_search(conn, lang)
    next_at = None
    if last:
        pause = timedelta(hours=catalog.refusal_pause_hours(conn)) if refused else COOLDOWN["watch"]
        next_at = to_iso(from_iso(last) + pause)
    return {
        "language": lang,
        "auto": auto_enabled(conn),
        "pools": pools,
        "estimated": estimated,
        "targets": POOL_TARGET,
        "low": [shelf for shelf, target in POOL_TARGET.items() if pools[shelf] < target],
        "searching": bool(job and job["status"] in ("queued", "running")),
        "job": job,
        "last_search_at": last,
        "youtube_refused": refused,
        "next_auto_at": next_at,
    }


def _due(conn: Connection, lang: str, shelf: str, at_end: bool) -> bool:
    last = _last(conn, lang, shelf)
    wait = AT_END_COOLDOWN if at_end else COOLDOWN[shelf]
    return not last or utc_now() - from_iso(last) >= wait


def maybe_top_up(
    conn: Connection, lang: str, *, force: bool = False, shelf: str | None = None, at_end: bool = False
) -> dict[str, Any]:
    """Queue background work if suggestions are running low. `force` = a button press (no cooldown)."""
    state = status(conn, lang)
    if state["searching"]:
        return {**state, "queued": False, "reason": "already searching"}
    if not force and not state["auto"]:
        return {**state, "queued": False, "reason": "automatic search is off"}
    wanted = set(POOL_TARGET) if force and not shelf else set(state["low"])
    if shelf and (force or at_end):
        wanted.add(shelf)
    if not force:
        wanted = {s for s in wanted if _due(conn, lang, s, at_end and s == shelf)}
    if state["youtube_refused"]:
        wanted.discard("watch")  # articles still come; YouTube gets a rest
    if wanted:
        for s in wanted:
            settings_store.put(conn, f"discover.auto_last.{lang}.{s}", to_iso(utc_now()))
        job_id = enqueue(
            conn, "update_content", {"lang": lang, "auto": not force, "videos": "watch" in wanted, "articles": "read" in wanted}
        )
        return {**status(conn, lang), "queued": True, "job_id": job_id, "shelves": sorted(wanted)}
    # Nothing to find: measure the best estimated videos instead, so the top of the list is exact.
    top = ranked(conn, lang, "watch")[:VERIFY_TOP]
    last_verify = settings_store.get(conn, f"discover.verify_last.{lang}")
    verify_due = not last_verify or utc_now() - from_iso(last_verify) >= VERIFY_COOLDOWN
    if any(i["estimated"] for i in top) and not state["youtube_refused"] and (verify_due or force) and state["auto"]:
        settings_store.put(conn, f"discover.verify_last.{lang}", to_iso(utc_now()))
        job_id = enqueue(conn, "verify_candidates", {"lang": lang, "limit": 12})
        return {**status(conn, lang), "queued": True, "job_id": job_id, "shelves": ["verify"]}
    reason = "enough suggestions" if not state["low"] else "searched recently"
    if state["youtube_refused"] and (shelf == "watch" or "watch" in state["low"]):
        reason = "YouTube asked to slow down"
    return {**state, "queued": False, "reason": reason}


def daily_refresh(conn: Connection, cfg: Any, lang: str) -> dict[str, Any]:
    """Once a day per language (the first time the app opens that day): adapt to yesterday.

    Your level estimate and taste are recomputed from what you did, every item is re-scored against them, and new
    videos and articles are looked for. It all runs as background jobs, one at a time, in short steps, so the app
    stays responsive; nothing waits for it.
    """
    from app.engine.profile import sync_language
    from app.services import recommend, taste
    from app.timeutil import local_today

    today = local_today().isoformat()
    key = f"daily.last.{lang}"
    if settings_store.get(conn, key) == today:
        return {"language": lang, "ran": False, "date": today, "reason": "already refreshed today"}
    settings_store.put(conn, key, today)
    sync_language(conn, cfg, lang)
    taste.invalidate(lang)
    recommend.invalidate()
    jobs = [enqueue(conn, "rescore", {"lang": lang})]
    found = maybe_top_up(conn, lang, force=True) if auto_enabled(conn) else {"queued": False, "reason": "automatic search is off"}
    if found.get("job_id"):
        jobs.append(found["job_id"])
    return {"language": lang, "ran": True, "date": today, "jobs": jobs, "search": found.get("reason") or "queued"}
