"""Apply the phone's outbox on the hub: each event exactly once, edits by last-writer-wins.

Events: {event_id, hlc, entity, entity_key, op, payload}
  lookup       you looked a word up on the phone (append)
  word_status  you changed a word's status or saved it (last writer wins by clock)
  activity     a timer session or a manual log (merged by its client_uuid)
  progress     how far you got in a book or volume (never goes backwards)
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import Connection, text

from app.services import vocab
from app.services.activity import MODALITY
from app.services.annotate import word_info
from app.services.reading import record_page_progress
from app.sync.hlc import Stamp
from app.timeutil import from_iso

ENTITIES = {"lookup", "word_status", "activity", "progress"}


class EventError(Exception):
    pass


def _millis(iso: str | None) -> int:
    return int(from_iso(iso).timestamp() * 1000) if iso else 0


def _lookup(conn: Connection, p: dict[str, Any], _hlc: str) -> str:
    info = word_info(conn, p["lang"], p["lemma"], p.get("reading", ""), list(dict.fromkeys([p["lemma"], *p.get("forms", [])])))
    vocab.record_lookup(conn, p["lang"], p["lemma"], p.get("reading", ""), p.get("pos", ""), info["rank"], info["model_p"])
    return "applied"


def _word_status(conn: Connection, p: dict[str, Any], hlc: str) -> str:
    lexeme_id = vocab.ensure_lexeme(conn, p["lang"], p["lemma"], p.get("reading", ""), p.get("pos", ""))
    row = conn.execute(
        text("SELECT updated_hlc, status_changed_at FROM user_words WHERE lexeme_id = :id"), {"id": lexeme_id}
    ).first()
    event_ms = Stamp.decode(hlc).millis
    if row:
        stored_hlc, changed_at = row
        if stored_hlc and stored_hlc >= hlc:
            return "superseded"
        if _millis(changed_at) > event_ms and not stored_hlc:
            return "superseded"  # changed on the laptop after the phone did
    vocab.set_status(
        conn, p["lang"], p["lemma"], p.get("reading", ""), p["status"], pos=p.get("pos", ""), save=bool(p.get("save")),
        context=p.get("context"),
    )
    conn.execute(text("UPDATE user_words SET updated_hlc = :h WHERE lexeme_id = :id"), {"h": hlc, "id": lexeme_id})
    return "applied"


def _activity(conn: Connection, p: dict[str, Any], _hlc: str) -> str:
    activity = p["activity"]
    if activity not in MODALITY:
        raise EventError(f"unknown activity '{activity}'")
    seconds = max(0, min(int(p.get("active_seconds", 0)), 24 * 3600))
    existing = conn.execute(text("SELECT id FROM activity_sessions WHERE client_uuid = :u"), {"u": p["client_uuid"]}).scalar()
    if existing:
        conn.execute(
            text(
                "UPDATE activity_sessions SET active_seconds = MAX(active_seconds, :s), "
                "ended_at = MAX(COALESCE(ended_at, ''), COALESCE(:e, '')) WHERE id = :id"
            ),
            {"s": seconds, "e": p.get("ended_at"), "id": existing},
        )
        return "merged"
    conn.execute(
        text(
            "INSERT INTO activity_sessions (language_code, activity, modality, tracking, title, started_at, ended_at, "
            "active_seconds, content_item_id, client_uuid) VALUES (:l, :a, :m, :t, :title, :s, :e, :sec, :item, :u)"
        ),
        {
            "l": p["lang"], "a": activity, "m": MODALITY[activity], "t": "manual" if p.get("manual") else "auto",
            "title": p.get("title"), "s": p["started_at"], "e": p.get("ended_at"), "sec": seconds,
            "item": p.get("content_item_id"), "u": p["client_uuid"],
        },
    )
    return "applied"


def _progress(conn: Connection, p: dict[str, Any], hlc: str) -> str:
    item_id = int(p["content_item_id"])
    if not conn.execute(text("SELECT 1 FROM content_items WHERE id = :i"), {"i": item_id}).first():
        raise EventError("no such item")
    record_page_progress(conn, item_id, int(p["page"]), int(p["total"]))
    conn.execute(
        text("UPDATE content_items SET progress_hlc = MAX(COALESCE(progress_hlc, ''), :h) WHERE id = :i"), {"h": hlc, "i": item_id}
    )
    return "applied"


APPLIERS = {"lookup": _lookup, "word_status": _word_status, "activity": _activity, "progress": _progress}


def apply_events(conn: Connection, device_id: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    results = {"applied": 0, "merged": 0, "superseded": 0, "duplicates": 0, "errors": []}
    for event in events[:2000]:
        event_id = str(event.get("event_id", ""))
        entity = event.get("entity")
        if not event_id or entity not in ENTITIES:
            results["errors"].append({"event_id": event_id, "error": f"unknown entity '{entity}'"})
            continue
        if conn.execute(text("SELECT 1 FROM sync_log WHERE event_id = :e"), {"e": event_id}).first():
            results["duplicates"] += 1
            continue
        hlc = str(event.get("hlc", ""))
        try:
            Stamp.decode(hlc)
            outcome = APPLIERS[entity](conn, event.get("payload") or {}, hlc)
        except (EventError, KeyError, ValueError, vocab.VocabError) as exc:
            results["errors"].append({"event_id": event_id, "error": str(exc)[:200]})
            continue
        conn.execute(
            text(
                "INSERT INTO sync_log (event_id, device_id, hlc, entity, entity_key, op, payload_json) "
                "VALUES (:e, :d, :h, :en, :k, :op, :p)"
            ),
            {
                "e": event_id, "d": device_id, "h": hlc, "en": entity, "k": str(event.get("entity_key", ""))[:200],
                "op": event.get("op", "insert") if event.get("op") in {"insert", "update", "delete"} else "insert",
                "p": json.dumps(event.get("payload") or {}, ensure_ascii=False),
            },
        )
        results[outcome] = results.get(outcome, 0) + 1
    results["seq"] = conn.execute(text("SELECT COALESCE(MAX(seq), 0) FROM sync_log")).scalar()
    return results


def changes_since(conn: Connection, since: str | None) -> dict[str, Any]:
    """Word statuses changed on any device since `since` (ISO time), so offline packs can recolour their words."""
    rows = conn.execute(
        text(
            "SELECT l.language_code, l.lemma, l.reading, w.status, w.p_known, COALESCE(w.status_changed_at, w.last_lookup_at) "
            "FROM user_words w JOIN lexemes l ON l.id = w.lexeme_id "
            "WHERE :since IS NULL OR COALESCE(w.status_changed_at, w.last_lookup_at, '') > :since"
        ),
        {"since": since},
    ).all()
    words = [{"lang": r[0], "lemma": r[1], "reading": r[2], "status": r[3], "p": r[4]} for r in rows]
    now = conn.execute(text("SELECT strftime('%Y-%m-%dT%H:%M:%fZ','now')")).scalar()
    return {"since": since, "until": now, "words": words}
