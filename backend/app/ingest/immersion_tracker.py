"""Import from the Immersion Tracker (D:\\Language-Immersion): immersion_log_<lang>.csv + settings.json.

Rules (ARCHITECTURE §6.10):
- `entry_id` becomes `external_ref`, so re-syncing a grown CSV never double-counts.
- `kind=baseline` becomes one pre-tracking session (`is_baseline = 1`).
- The session date is the tracker's `date`; `logged_at` only places it within that day.
- A video logged twice on the same day, within less time than its own length, is a
  probable double-log: it is recorded as a flag and not counted until you confirm it.
- YouTube rows also create a `content_items` row (and a channel `collections` row) so
  their subtitles can be analysed later.
"""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, text

from app.db import settings_store
from app.timeutil import local_noon_utc, to_iso

REQUIRED_COLUMNS = {"entry_id", "kind", "category", "date", "title", "duration_seconds", "logged_at"}
CATEGORY_MAP = {
    "youtube": ("video", "listening"),
    "watching": ("video", "listening"),
    "listening": ("audio", "listening"),
    "reading": ("reading", "reading"),
    "speaking": ("conversation", "speaking"),
}
DEFAULT_TITLES = {
    "youtube": "YouTube video",
    "watching": "Watching session",
    "listening": "Listening session",
    "reading": "Reading session",
    "speaking": "Speaking session",
}
CONFIRMED_KEY = "tracker_confirmed_duplicates"


class NotATrackerFile(ValueError):
    pass


@dataclass
class Flag:
    entry_id: str
    language: str
    date: str
    title: str
    reason: str


@dataclass
class FileResult:
    language: str
    file: str
    status: str  # imported | unchanged | missing
    rows: int = 0
    imported: int = 0
    already_present: int = 0
    duplicates: list[Flag] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def import_tracker_folder(conn: Connection, data_dir: Path, folder: Path, languages: list[str]) -> dict[str, Any]:
    if not folder.is_dir():
        raise FileNotFoundError(f"Immersion Tracker folder not found: {folder}")
    results: list[FileResult] = []
    for code in languages:
        path = folder / f"immersion_log_{code}.csv"
        if path.exists():
            results.append(import_tracker_file(conn, data_dir, path, code))
        else:
            results.append(FileResult(code, str(path), "missing"))
    goals = _import_goals(conn, folder / "settings.json", languages)
    return {"folder": str(folder), "files": [asdict(r) for r in results], "goals_imported": goals}


def import_tracker_file(conn: Connection, data_dir: Path, path: Path, language: str) -> FileResult:
    raw = path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    result = FileResult(language, str(path), "imported")

    already = conn.execute(
        text("SELECT id FROM import_batches WHERE file_sha256 = :sha AND status = 'imported' LIMIT 1"), {"sha": sha}
    ).first()
    if already:
        result.status = "unchanged"
        return result

    rows = list(csv.DictReader(raw.decode("utf-8-sig").splitlines()))
    header = set(rows[0].keys()) if rows else set()
    if rows and not REQUIRED_COLUMNS <= header:
        raise NotATrackerFile(f"{path.name} is missing columns: {sorted(REQUIRED_COLUMNS - header)}")

    imports_dir = data_dir / "imports"
    imports_dir.mkdir(parents=True, exist_ok=True)
    stored = imports_dir / f"{sha[:12]}_{path.name}"
    shutil.copyfile(path, stored)

    batch_id = conn.execute(
        text(
            "INSERT INTO import_batches (filename, file_sha256, stored_path, column_map_json, default_language, "
            "row_count, status) VALUES (:name, :sha, :stored, :map, :lang, :count, 'preview')"
        ),
        {
            "name": path.name,
            "sha": sha,
            "stored": str(stored.relative_to(data_dir)),
            "map": json.dumps({"format": "immersion-tracker-v1"}),
            "lang": language,
            "count": len(rows),
        },
    ).lastrowid

    confirmed = set(settings_store.get(conn, CONFIRMED_KEY, []) or [])
    seen_videos: dict[str, tuple[date, datetime | None, int]] = {}
    result.rows = len(rows)

    for index, row in enumerate(rows):
        status, message = "imported", None
        try:
            flag = _duplicate_check(row, seen_videos)
            if flag and row["entry_id"] not in confirmed:
                status, message = "duplicate", flag
                result.duplicates.append(
                    Flag(row["entry_id"], language, row.get("date", ""), row.get("title", ""), flag)
                )
            else:
                inserted = _insert_session(conn, row, language, batch_id)
                if inserted:
                    result.imported += 1
                else:
                    status, message = "skipped", "already imported"
                    result.already_present += 1
        except (ValueError, KeyError) as exc:
            status, message = "error", str(exc)
            result.errors.append(f"row {index + 2}: {exc}")
        conn.execute(
            text(
                "INSERT INTO import_rows (batch_id, row_index, raw_json, status, message) "
                "VALUES (:batch, :idx, :raw, :status, :msg)"
            ),
            {"batch": batch_id, "idx": index, "raw": json.dumps(row, ensure_ascii=False), "status": status, "msg": message},
        )

    conn.execute(
        text(
            "UPDATE import_batches SET status = 'imported', imported_count = :imp, skipped_count = :skip, "
            "errors_json = :errs WHERE id = :id"
        ),
        {
            "imp": result.imported,
            "skip": result.rows - result.imported,
            "errs": json.dumps(result.errors),
            "id": batch_id,
        },
    )
    return result


def pending_flags(conn: Connection) -> list[dict[str, Any]]:
    confirmed = set(settings_store.get(conn, CONFIRMED_KEY, []) or [])
    rows = conn.execute(
        text(
            "SELECT r.raw_json, r.message, b.default_language FROM import_rows r "
            "JOIN import_batches b ON b.id = r.batch_id WHERE r.status = 'duplicate' ORDER BY r.id"
        )
    ).all()
    flags: dict[str, dict[str, Any]] = {}
    for raw_json, message, language in rows:
        row = json.loads(raw_json)
        entry = row["entry_id"]
        if entry in confirmed:
            continue
        flags[entry] = {
            "entry_id": entry,
            "language": language,
            "date": row.get("date"),
            "title": row.get("title"),
            "minutes": round(int(float(row.get("duration_seconds") or 0)) / 60),
            "reason": message,
        }
    return list(flags.values())


def confirm_duplicate(conn: Connection, entry_id: str) -> bool:
    """Count a flagged row after all. Returns False if no such flag exists."""
    found = conn.execute(
        text(
            "SELECT r.id, r.raw_json, r.batch_id, b.default_language FROM import_rows r "
            "JOIN import_batches b ON b.id = r.batch_id "
            "WHERE r.status = 'duplicate' AND json_extract(r.raw_json, '$.entry_id') = :e ORDER BY r.id DESC LIMIT 1"
        ),
        {"e": entry_id},
    ).first()
    if not found:
        return False
    row_id, raw_json, batch_id, language = found
    confirmed = list(settings_store.get(conn, CONFIRMED_KEY, []) or [])
    if entry_id not in confirmed:
        confirmed.append(entry_id)
        settings_store.put(conn, CONFIRMED_KEY, confirmed)
    _insert_session(conn, json.loads(raw_json), language, batch_id)
    conn.execute(
        text("UPDATE import_rows SET status = 'imported', message = 'confirmed by user' WHERE status = 'duplicate' "
             "AND json_extract(raw_json, '$.entry_id') = :e"),
        {"e": entry_id},
    )
    return True


# --------------------------------------------------------------------------- helpers


def _parse_logged(value: str | None) -> datetime | None:
    value = (value or "").strip()
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S") if value else None


def _seconds(row: dict[str, str]) -> int:
    seconds = int(float(row.get("duration_seconds") or 0))
    if seconds <= 0:
        raise ValueError("duration_seconds must be positive")
    return seconds


def _duplicate_check(row: dict[str, str], seen: dict[str, tuple[date, datetime | None, int]]) -> str | None:
    video_id = (row.get("video_id") or "").strip()
    if row.get("kind") != "session" or not video_id:
        return None
    day = date.fromisoformat(row["date"])
    logged = _parse_logged(row.get("logged_at"))
    seconds = _seconds(row)
    previous = seen.get(video_id)
    seen[video_id] = (day, logged, seconds)
    if previous and previous[0] == day and previous[1] and logged:
        gap = (logged - previous[1]).total_seconds()
        if 0 <= gap < seconds:
            return f"same video logged twice on {day.isoformat()}, {int(gap)} s apart"
    return None


def _start_time(row: dict[str, str], seconds: int) -> datetime:
    """UTC start of a session, kept on the tracker's `date`."""
    logged = _parse_logged(row.get("logged_at"))
    if row.get("kind") == "baseline":
        return (logged or datetime.now()).astimezone()
    day = date.fromisoformat(row["date"])
    if logged and logged.date() == day:
        start_local = max(logged - timedelta(seconds=seconds), datetime.combine(day, time(0, 0)))
        return start_local.astimezone()
    return local_noon_utc(day)


def _insert_session(conn: Connection, row: dict[str, str], language: str, batch_id: int) -> bool:
    kind = (row.get("kind") or "").strip()
    seconds = _seconds(row)
    start = _start_time(row, seconds)
    end = start + timedelta(seconds=seconds)
    title = (row.get("title") or "").strip()
    url = (row.get("url") or "").strip() or None
    category = (row.get("category") or "").strip()

    if kind == "baseline":
        activity, modality, is_baseline, content_id = "other", "mixed", 1, None
        title = title or "Immersion before tracking started"
    elif kind == "session":
        if category not in CATEGORY_MAP:
            raise ValueError(f"unknown category '{category}'")
        activity, modality = CATEGORY_MAP[category]
        is_baseline = 0
        if title.lower().startswith(("http://", "https://")):
            url = url or title
            title = DEFAULT_TITLES[category]
        title = title or DEFAULT_TITLES[category]
        content_id = _content_item(conn, row, language, title, seconds) if row.get("video_id") else None
    else:
        raise ValueError(f"unknown kind '{kind}'")

    inserted = conn.execute(
        text(
            "INSERT OR IGNORE INTO activity_sessions (language_code, activity, modality, tracking, content_item_id, "
            "title, started_at, ended_at, active_seconds, is_baseline, notes, import_batch_id, external_ref) "
            "VALUES (:lang, :activity, :modality, 'import', :content, :title, :start, :end, :seconds, :baseline, "
            ":notes, :batch, :ref)"
        ),
        {
            "lang": language,
            "activity": activity,
            "modality": modality,
            "content": content_id,
            "title": title,
            "start": to_iso(start),
            "end": to_iso(end),
            "seconds": seconds,
            "baseline": is_baseline,
            "notes": url if url and not content_id else None,
            "batch": batch_id,
            "ref": row["entry_id"],
        },
    ).rowcount
    return inserted == 1


def _content_item(conn: Connection, row: dict[str, str], language: str, title: str, seconds: int) -> int:
    from app.services.content import upsert_youtube  # local import: content pulls in the NLP stack

    return upsert_youtube(
        conn,
        language,
        row["video_id"].strip(),
        title=title,
        channel=(row.get("channel") or "").strip() or None,
        duration=seconds,
        origin="csv_import",
        status="finished",
        finished=row.get("date"),
    )


def _import_goals(conn: Connection, settings_path: Path, languages: list[str]) -> dict[str, int] | None:
    """Copy daily goals from the tracker unless you've already edited them in Lingo OS."""
    if not settings_path.exists() or settings_store.get(conn, "goals_user_edited", False):
        return None
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    tracker_goals = {
        code: int(value)
        for code, value in (data.get("goals") or {}).items()
        if code in languages and isinstance(value, (int, float)) and 1 <= value <= 720
    }
    if not tracker_goals:
        return None
    goals = dict(settings_store.get(conn, "goals", {}) or {})
    goals.update(tracker_goals)
    settings_store.put(conn, "goals", goals)
    return tracker_goals
