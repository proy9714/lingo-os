"""Words move by themselves as you meet them in what you watch and read: no flashcards, no reviews.

A word you're learning becomes familiar, and a familiar word becomes known, once it has stuck: you've met it on
several different days in content you actually consumed, spaced out, without needing to look it up. A word you keep
looking up after it became known or familiar moves back a step. How quickly words move depends on you: the memory
model behind this (engine/memory.py) is fitted to your own history, and you can set the pace (cautious, balanced,
eager) or turn automatic moves off in Words.

Any status you set yourself wins: a word you move by hand is never moved back against you for 30 days (and after
that only if you keep looking it up), and moving an automatic step back tells the model it was too early.

Only content where the app knows what you met counts: videos, audio, podcasts and articles, each in proportion to how
much of it you got through (a whole book or manga volume lists every word in it, not the pages you read).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import Connection, text

from app.db import settings_store
from app.engine import memory
from app.timeutil import from_iso, to_iso, utc_now

COUNTED_TYPES = memory.COUNTED_TYPES
STATUS_P = {"learning": 0.3, "familiar": 0.75, "known": 0.98}
MOVES_KEY = "word_moves.{lang}"
KEEP_MOVES = timedelta(days=7)


def evaluate(conn: Connection, lang: str) -> list[dict[str, Any]]:
    """Which words should move now (up or down), with the evidence for it."""
    prefs = memory.preferences(conn)
    if not prefs["auto"]:
        return []
    now = utc_now()
    out = []
    for word in memory.load_words(conn, lang):
        target = memory.next_move(word, prefs, now)
        if not target:
            continue
        out.append(
            {
                "lexeme_id": word.lexeme_id,
                "lemma": word.lemma,
                "reading": word.reading,
                "from": word.status,
                "to": target,
                "direction": "down" if (word.status, target) in {("known", "familiar"), ("familiar", "learning")} else "up",
                "days": len(set(word.evidence_days)),
                "times": round(word.times, 1),
                "lookups": word.lapses,
            }
        )
    return out


def promote(conn: Connection, lang: str) -> list[dict[str, Any]]:
    """Move every word that should move, and remember the moves (Today shows them, each with a way back).

    Runs once a day (topup.daily_refresh); refits the memory model to your history first when it's a day old."""
    memory.fit(conn, lang)
    moves = evaluate(conn, lang)
    now = to_iso(utc_now())
    for move in moves:
        conn.execute(
            text("UPDATE user_words SET status = :s, p_known = :p, status_changed_at = :now WHERE lexeme_id = :w"),
            {"s": move["to"], "p": STATUS_P[move["to"]], "now": now, "w": move["lexeme_id"]},
        )
        why = f"met on {move['days']} days" if move["direction"] == "up" else f"looked up {move['lookups']} times"
        conn.execute(
            text("INSERT INTO word_events (lexeme_id, event, value) VALUES (:w, 'status_change', :v)"),
            {"w": move["lexeme_id"], "v": f"{move['to']} (automatic: {why})"},
        )
        _stamp(conn, move["lexeme_id"])
    if moves:
        key = MOVES_KEY.format(lang=lang)
        stored = settings_store.get(conn, key) or {}
        cutoff = utc_now() - KEEP_MOVES
        kept = [m for m in stored.get("moves", []) if m.get("at") and from_iso(m["at"]) > cutoff]
        fresh = {m["lexeme_id"] for m in moves}
        kept = [m for m in kept if m["lexeme_id"] not in fresh]  # a word's latest move replaces an older one
        settings_store.put(conn, key, {"at": now, "moves": [{**m, "at": now} for m in moves] + kept})
    return moves


def _stamp(conn: Connection, lexeme_id: int) -> None:
    """Give an automatic move a sync clock, so a phone's older change can't overwrite it (sync/apply.py)."""
    try:
        from app.services.vocab import stamp_hlc
    except ImportError:  # pragma: no cover
        return
    stamp_hlc(conn, lexeme_id)


def recent_moves(conn: Connection, lang: str, days: int = 7) -> dict[str, Any]:
    """The automatic moves of the last `days` days, with each word's current status so undone ones can show it."""
    stored = settings_store.get(conn, MOVES_KEY.format(lang=lang)) or {}
    cutoff = utc_now() - timedelta(days=days)
    moves = [m for m in stored.get("moves", []) if from_iso(m.get("at") or stored.get("at") or "1970-01-01T00:00:00Z") > cutoff]
    if not moves:
        return {"at": None, "moves": []}
    ids = [m["lexeme_id"] for m in moves]
    current = dict(
        conn.execute(text("SELECT lexeme_id, status FROM user_words WHERE lexeme_id IN (" + ",".join(str(int(i)) for i in ids) + ")")).all()
    )
    return {
        "at": stored.get("at"),
        "moves": [{"direction": "up", **m, "status": current.get(m["lexeme_id"], m["to"])} for m in moves],
    }


def explain(conn: Connection, lang: str, lexeme_id: int) -> dict[str, Any] | None:
    """Where one word stands and why, in plain words."""
    state = memory.word_state(conn, lang, [lexeme_id]).get(lexeme_id)
    if not state:
        return None
    return memory.explain(state, memory.preferences(conn))
