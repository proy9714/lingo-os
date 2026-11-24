"""Words move up by themselves as you meet them in what you watch and read: no flashcards, no reviews.

A word you're learning becomes familiar, and a familiar word becomes known, once you've met it on several different
days in content you actually consumed, without needing to look it up. Looking it up again holds it back. Any status
you set yourself wins: a word you move back down has to earn the step up again from that moment.

  learning → familiar  met on 3+ days (4+ times in all) since its status was set, no lookup in the last 2 days
  familiar → known     met on 3+ more days spread over 7+ days since it became familiar, no lookup since then

Only content where the app knows what you met counts: videos, audio and articles (a whole book or manga volume lists
every word in it, not the pages you read).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import Connection, text

from app.db import settings_store
from app.timeutil import from_iso, local_day, local_today, to_iso, utc_now

COUNTED_TYPES = ("youtube", "video", "audio", "podcast_episode", "article", "text")
RULES = {
    "learning": {"to": "familiar", "days": 3, "occurrences": 4, "span_days": 0, "quiet_days": 2},
    "familiar": {"to": "known", "days": 3, "occurrences": 3, "span_days": 7, "quiet_days": None},
}
STATUS_P = {"familiar": 0.75, "known": 0.98}
MOVES_KEY = "word_moves.{lang}"


def _encounters(conn: Connection, lexeme_id: int, since: str) -> list[tuple[str, int]]:
    """(local day, times met) for each session after `since` in content containing the word."""
    types = ", ".join(f"'{t}'" for t in COUNTED_TYPES)
    rows = conn.execute(
        text(
            "SELECT s.started_at, cl.count FROM content_lemmas cl "
            "JOIN content_items ci ON ci.id = cl.content_item_id "
            "JOIN activity_sessions s ON s.content_item_id = ci.id "
            f"WHERE cl.lexeme_id = :w AND ci.type IN ({types}) AND s.is_baseline = 0 AND s.active_seconds >= 60 "
            "AND s.started_at > :since"
        ),
        {"w": lexeme_id, "since": since},
    ).all()
    return [(local_day(r[0]).isoformat(), int(r[1] or 1)) for r in rows]


def _lookup_days(conn: Connection, lexeme_id: int, since: str) -> set[str]:
    rows = conn.execute(
        text("SELECT created_at FROM word_events WHERE lexeme_id = :w AND event = 'lookup' AND created_at > :since"),
        {"w": lexeme_id, "since": since},
    ).all()
    return {local_day(r[0]).isoformat() for r in rows}


def evaluate(conn: Connection, lang: str) -> list[dict[str, Any]]:
    """Which learning / familiar words have earned the next step, and the evidence for it."""
    rows = conn.execute(
        text(
            "SELECT w.lexeme_id, l.lemma, l.reading, w.status, COALESCE(w.status_changed_at, w.first_seen_at), w.last_lookup_at "
            "FROM user_words w JOIN lexemes l ON l.id = w.lexeme_id "
            "WHERE l.language_code = :l AND w.status IN ('learning', 'familiar')"
        ),
        {"l": lang},
    ).all()
    today = local_today()
    ready = []
    for lexeme_id, lemma, reading, status, since, last_lookup in rows:
        rule = RULES[status]
        since = since or "1970-01-01T00:00:00.000Z"
        looked_up = _lookup_days(conn, lexeme_id, since)
        if rule["quiet_days"] is None and looked_up:
            continue  # familiar → known needs no lookups at all since it became familiar
        if rule["quiet_days"] and last_lookup and (today - local_day(last_lookup)).days < rule["quiet_days"]:
            continue
        met = [(day, n) for day, n in _encounters(conn, lexeme_id, since) if day not in looked_up]
        days = sorted({day for day, _ in met})
        if len(days) < rule["days"] or sum(n for _, n in met) < rule["occurrences"]:
            continue
        if rule["span_days"] and (from_iso(days[-1] + "T00:00:00Z") - from_iso(days[0] + "T00:00:00Z")).days < rule["span_days"]:
            continue
        ready.append(
            {"lexeme_id": lexeme_id, "lemma": lemma, "reading": reading, "from": status, "to": rule["to"],
             "days": len(days), "times": sum(n for _, n in met)}
        )
    return ready


def promote(conn: Connection, lang: str) -> list[dict[str, Any]]:
    """Move up every word that has earned it, and remember the moves (Today shows them, with a way back)."""
    moves = evaluate(conn, lang)
    now = to_iso(utc_now())
    for move in moves:
        conn.execute(
            text("UPDATE user_words SET status = :s, p_known = :p, status_changed_at = :now WHERE lexeme_id = :w"),
            {"s": move["to"], "p": STATUS_P[move["to"]], "now": now, "w": move["lexeme_id"]},
        )
        conn.execute(
            text("INSERT INTO word_events (lexeme_id, event, value) VALUES (:w, 'status_change', :v)"),
            {"w": move["lexeme_id"], "v": f"{move['to']} (automatic: met on {move['days']} days)"},
        )
    if moves:
        settings_store.put(conn, MOVES_KEY.format(lang=lang), {"at": now, "moves": moves})
    return moves


def recent_moves(conn: Connection, lang: str, days: int = 7) -> dict[str, Any]:
    """The last automatic moves (within `days`), with each word's current status so undone ones can show it."""
    stored = settings_store.get(conn, MOVES_KEY.format(lang=lang)) or {}
    if not stored.get("at") or utc_now() - from_iso(stored["at"]) > timedelta(days=days):
        return {"at": None, "moves": []}
    ids = [m["lexeme_id"] for m in stored.get("moves", [])]
    current = dict(
        conn.execute(text("SELECT lexeme_id, status FROM user_words WHERE lexeme_id IN (" + ",".join(str(int(i)) for i in ids) + ")")).all()
    ) if ids else {}
    return {"at": stored["at"], "moves": [{**m, "status": current.get(m["lexeme_id"], m["to"])} for m in stored["moves"]]}
