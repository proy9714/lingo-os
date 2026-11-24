"""Where a learner starts in a language: the level they think they're at, the hours they spent before Lingo OS, and
the history they import from a CSV. All three feed the starting estimate until a Level Lab test measures them.

CSV formats (detected from the header):
  Immersion Tracker  entry_id, kind, category, date, title, duration_seconds, logged_at (+ url, video_id, channel)
  Simple             date, title or url, minutes or seconds or duration (+ url, channel, category); one row per session
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, text

from app.config import AppConfig
from app.db import settings_store
from app.engine.profile import SELF_LEVEL_WORDS, get_profile, self_level, sync_language
from app.ingest import immersion_tracker as tracker
from app.ingest.youtube import parse_video_id
from app.sync.ids import new_ulid
from app.timeutil import to_iso, utc_now

MANUAL_BASELINE_REF = "baseline:{lang}"
MAX_BASELINE_HOURS = 20_000


class StartingPointError(ValueError):
    pass


# ------------------------------------------------------------------ level and hours


def summary(conn: Connection, lang: str) -> dict[str, Any]:
    rows = conn.execute(
        text(
            "SELECT tracking, COALESCE(SUM(active_seconds), 0) FROM activity_sessions "
            "WHERE language_code = :l AND is_baseline = 1 GROUP BY tracking"
        ),
        {"l": lang},
    ).all()
    by = {r[0]: int(r[1]) for r in rows}
    sessions = dict(
        conn.execute(
            text(
                "SELECT tracking = 'import', COALESCE(SUM(active_seconds), 0) FROM activity_sessions "
                "WHERE language_code = :l AND is_baseline = 0 GROUP BY 1"
            ),
            {"l": lang},
        ).all()
    )
    tracked, imported_sessions = int(sessions.get(0, 0)), int(sessions.get(1, 0))
    profile = get_profile(conn, lang) or {}
    return {
        "language": lang,
        "self_level": self_level(conn, lang),
        "levels": list(SELF_LEVEL_WORDS),
        "measured": bool(profile.get("measured")),
        "baseline_hours": round(sum(by.values()) / 3600, 1),
        "imported_baseline_hours": round(by.get("import", 0) / 3600, 1),
        "tracked_hours": round(tracked / 3600, 1),
        "imported_session_hours": round(imported_sessions / 3600, 1),
        "has_start": bool(self_level(conn, lang) or by or tracked or imported_sessions or profile.get("measured")),
    }


def set_level(conn: Connection, cfg: AppConfig, lang: str, level: str | None) -> dict[str, Any]:
    if level is not None and level not in SELF_LEVEL_WORDS:
        raise StartingPointError(f"unknown level '{level}'")
    settings_store.put(conn, f"self_level.{lang}", level)
    _refresh(conn, cfg, lang)
    return summary(conn, lang)


def set_baseline_hours(conn: Connection, cfg: AppConfig, lang: str, hours: float) -> dict[str, Any]:
    """Your total hours in the language before Lingo OS. Hours already imported from a CSV count toward it."""
    if not 0 <= hours <= MAX_BASELINE_HOURS:
        raise StartingPointError(f"hours must be between 0 and {MAX_BASELINE_HOURS}")
    ref = MANUAL_BASELINE_REF.format(lang=lang)
    conn.execute(
        text("DELETE FROM activity_sessions WHERE language_code = :l AND tracking = 'manual' AND external_ref = :r"),
        {"l": lang, "r": ref},
    )
    imported = conn.execute(
        text(
            "SELECT COALESCE(SUM(active_seconds), 0) FROM activity_sessions "
            "WHERE language_code = :l AND is_baseline = 1 AND tracking = 'import'"
        ),
        {"l": lang},
    ).scalar() or 0
    extra = max(0, round(hours * 3600) - int(imported))
    if extra:
        now = to_iso(utc_now())
        conn.execute(
            text(
                "INSERT INTO activity_sessions (language_code, activity, modality, tracking, title, started_at, ended_at, "
                "active_seconds, is_baseline, external_ref, client_uuid) VALUES (:l, 'other', 'mixed', 'manual', "
                "'Immersion before Lingo OS', :t, :t, :s, 1, :r, :u)"
            ),
            {"l": lang, "t": now, "s": extra, "r": ref, "u": new_ulid()},
        )
    _refresh(conn, cfg, lang)
    return summary(conn, lang)


def _refresh(conn: Connection, cfg: AppConfig, lang: str) -> None:
    """A new starting estimate re-scores everything in the language (in the background) and re-ranks it."""
    from app.jobs.runner import enqueue
    from app.services import recommend

    sync_language(conn, cfg, lang)
    enqueue(conn, "rescore", {"lang": lang})
    recommend.invalidate()


# ------------------------------------------------------------------ CSV history

SIMPLE_ALIASES = {
    "date": ("date", "day", "watched_on", "watched", "datum", "fecha"),
    "title": ("title", "name", "video", "video_title"),
    "url": ("url", "link", "video_url", "youtube"),
    "minutes": ("minutes", "duration_minutes", "mins", "min"),
    "seconds": ("seconds", "duration_seconds", "secs"),
    "duration": ("duration", "length", "time"),
    "channel": ("channel", "creator", "author", "uploader"),
    "category": ("category", "type", "activity", "kind"),
}
CATEGORY_WORDS = {
    "youtube": ("youtube", "video", "videos", "watching", "watch", "tv", "film", "movie", "series", "netflix"),
    "listening": ("listening", "podcast", "audio", "audiobook", "music", "radio"),
    "reading": ("reading", "book", "article", "manga", "read"),
    "speaking": ("speaking", "conversation", "class", "lesson", "tutor"),
}
TEMPLATE = (
    "date,title,minutes,url,channel,category\n"
    "2026-03-01,Easy German 412 – Street interviews,18,https://www.youtube.com/watch?v=VIDEOID,Easy German,video\n"
    "2026-03-02,Podcast episode 12,35,,,podcast\n"
    "2026-03-02,A chapter of a book,40,,,reading\n"
)


def _column(header: dict[str, str], key: str) -> str | None:
    return next((header[a] for a in SIMPLE_ALIASES[key] if a in header), None)


def _parse_date(value: str) -> date:
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value[:19], fmt).date()
        except ValueError:
            continue
    raise ValueError(f"can't read the date '{value}' (use YYYY-MM-DD)")


def _duration_text(value: str, unit_seconds: int) -> int:
    """'18' (in the column's unit), '1:10:00' / '70:00', '1h 10m', '45m', '2h' → seconds."""
    value = value.strip().lower().replace(",", ".")
    if re.fullmatch(r"\d+(\.\d+)?", value):
        return int(float(value) * unit_seconds)
    if re.fullmatch(r"\d+(:\d{1,2}){1,2}", value):
        parts = [int(p) for p in value.split(":")]
        return parts[0] * 3600 + parts[1] * 60 + parts[2] if len(parts) == 3 else parts[0] * 60 + parts[1]
    h = re.search(r"(\d+(?:\.\d+)?)\s*h", value)
    m = re.search(r"(\d+)\s*m", value)
    s = re.search(r"(\d+)\s*s\b", value)
    if h or m or s:
        return int(float(h[1]) * 3600 if h else 0) + (int(m[1]) * 60 if m else 0) + (int(s[1]) if s else 0)
    raise ValueError(f"can't read the duration '{value}'")


def _parse_seconds(row: dict[str, str], cols: dict[str, str | None]) -> int:
    for key, unit in (("seconds", 1), ("minutes", 60), ("duration", 60)):
        column = cols[key]
        if column and (row.get(column) or "").strip():
            return _duration_text(row[column], unit)
    raise ValueError("no duration (minutes, seconds or duration)")


def _category(value: str, url: str | None) -> str:
    low = value.strip().lower()
    for category, words in CATEGORY_WORDS.items():
        if low in words:
            return category
    return "youtube" if url and parse_video_id(url) else "watching"


def convert_simple(rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[str]]:
    """Simple CSV rows → Immersion Tracker rows (the importer's own format). Returns (rows, errors)."""
    if not rows:
        return [], []
    header = {name.strip().lower(): name for name in rows[0].keys() if name}
    cols = {key: _column(header, key) for key in SIMPLE_ALIASES}
    if not cols["date"] or not (cols["title"] or cols["url"]) or not (cols["minutes"] or cols["seconds"] or cols["duration"]):
        raise StartingPointError(
            "The CSV needs at least a date column, a title or url column, and a minutes, seconds or duration column."
        )
    out, errors = [], []
    for index, row in enumerate(rows, start=2):
        try:
            day = _parse_date(row.get(cols["date"]) or "")
            seconds = _parse_seconds(row, cols)
            if seconds <= 0:
                raise ValueError("the duration is zero")
            url = (row.get(cols["url"]) or "").strip() if cols["url"] else ""
            title = (row.get(cols["title"]) or "").strip() if cols["title"] else ""
            video_id = parse_video_id(url) if url else None
            category = _category((row.get(cols["category"]) or "") if cols["category"] else "", url)
            if category == "youtube" and not video_id:
                category = "watching"
            key = f"{day}|{title}|{url}|{seconds}|{index}"
            out.append(
                {
                    "entry_id": "csv-" + hashlib.sha1(key.encode()).hexdigest()[:16],
                    "kind": "session", "category": category, "date": day.isoformat(), "url": url,
                    "video_id": video_id or "", "title": title or url, "channel": (row.get(cols["channel"]) or "").strip() if cols["channel"] else "",
                    "duration_seconds": str(seconds), "duration_hm": "", "logged_at": f"{day.isoformat()} 12:00:00",
                }
            )
        except (ValueError, TypeError) as exc:
            errors.append(f"row {index}: {exc}")
    return out, errors


def import_csv(conn: Connection, cfg: AppConfig, lang: str, filename: str, data: bytes) -> dict[str, Any]:
    """Import a history CSV for one language and report what was read, added and will be analysed."""
    from app.jobs.runner import enqueue

    try:
        decoded = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        decoded = data.decode("cp1252", errors="replace")
    sample = decoded[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.DictReader(io.StringIO(decoded), dialect=dialect))
    if not rows:
        raise StartingPointError("The file has no rows.")
    header = set(rows[0].keys())
    if tracker.REQUIRED_COLUMNS <= header:
        fmt, converted, errors = "immersion-tracker", rows, []
    else:
        fmt = "simple"
        converted, errors = convert_simple(rows)
        if not converted:
            raise StartingPointError("No row could be read. " + "; ".join(errors[:3]))

    # the importer keeps its own copy in data/imports; this converted file is only passed to it
    staging = cfg.data_dir / "cache" / "imports"
    staging.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^\w.-]+", "_", Path(filename).stem)[:60] or "history"
    target = staging / f"{hashlib.sha256(data).hexdigest()[:12]}_{stem}.csv"
    columns = list(converted[0].keys())
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(converted)
    target.write_text(buffer.getvalue(), encoding="utf-8")

    last_batch = conn.execute(text("SELECT COALESCE(MAX(id), 0) FROM import_batches")).scalar()
    result = tracker.import_tracker_file(conn, cfg.data_dir, target, lang)
    target.unlink(missing_ok=True)
    conn.execute(  # show the file as you named it, and how it was read
        text("UPDATE import_batches SET filename = :f, column_map_json = :m WHERE id > :b"),
        {"f": filename[:200], "m": json.dumps({"format": fmt}), "b": last_batch},
    )
    videos = {r.get("video_id") for r in converted if r.get("video_id")}
    time_only = sum(1 for r in converted if not r.get("video_id"))
    job_id = enqueue(conn, "fetch_history_captions", {"lang": lang}) if videos else None
    _refresh(conn, cfg, lang)
    return {
        "format": fmt,
        "file": filename,
        "status": result.status,
        "rows": len(rows),
        "imported": result.imported,
        "already_present": result.already_present,
        "duplicates": len(result.duplicates),
        "errors": errors + result.errors,
        "videos": len(videos),
        "time_only_rows": time_only,
        "analysis_job": job_id,
    }


def history(conn: Connection, lang: str) -> dict[str, Any]:
    """Past imports for a language, and how far the analysis of the imported videos has got."""
    from app.engine.evidence import content_evidence
    from app.jobs.runner import latest_job

    batches = conn.execute(
        text(
            "SELECT id, filename, row_count, imported_count, skipped_count, errors_json, created_at, column_map_json "
            "FROM import_batches WHERE default_language = :l AND status = 'imported' ORDER BY id DESC LIMIT 20"
        ),
        {"l": lang},
    ).all()
    evidence = content_evidence(conn, lang)
    pending = conn.execute(
        text(
            "SELECT COUNT(*) FROM content_items ci WHERE ci.language_code = :l AND ci.source = 'youtube' "
            "AND ci.analysis_status != 'done' AND EXISTS (SELECT 1 FROM activity_sessions s WHERE s.content_item_id = ci.id) "
            "AND COALESCE(json_extract(ci.metadata_json, '$.captions'), '') != 'none'"
        ),
        {"l": lang},
    ).scalar() or 0
    no_captions = conn.execute(
        text(
            "SELECT COUNT(*) FROM content_items ci WHERE ci.language_code = :l AND ci.source = 'youtube' "
            "AND json_extract(ci.metadata_json, '$.captions') = 'none' "
            "AND EXISTS (SELECT 1 FROM activity_sessions s WHERE s.content_item_id = ci.id)"
        ),
        {"l": lang},
    ).scalar() or 0
    return {
        "imports": [
            {
                "id": r[0], "file": r[1], "rows": r[2], "imported": r[3], "skipped": r[4], "errors": len(json.loads(r[5] or "[]")),
                "at": r[6], "format": json.loads(r[7] or "{}").get("format", "immersion-tracker-v1"),
            }
            for r in batches
        ],
        "videos": {
            "watched": evidence.get("videos_watched", 0),
            "analysed": evidence.get("videos_analysed", 0),
            "no_captions": int(no_captions),
            "waiting": int(pending),
        },
        "job": latest_job(conn, "fetch_history_captions"),
    }
