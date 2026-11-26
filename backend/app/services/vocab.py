"""Your relationship with words: lexemes, statuses, lookups, saved sentences (no flashcards, ever)."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import Connection, bindparam, text

from app.languages.base import lexeme_key
from app.sync.hlc import HybridClock
from app.timeutil import to_iso, utc_now

STATUSES = ("seen", "learning", "familiar", "known", "ignored")
STATUS_P = {"learning": 0.3, "familiar": 0.75, "known": 0.98, "ignored": 1.0}


class VocabError(ValueError):
    pass


# Every status change made here (by you, by an automatic move, by a test) gets a sync clock stamp, so a change the
# phone made earlier and sends later can't overwrite it: last writer wins (sync/apply.py). "HUB" stands for this
# laptop or server; phones stamp with their own device id.
_CLOCK = HybridClock("HUB")


def stamp_hlc(conn: Connection, lexeme_id: int) -> str:
    stamp = _CLOCK.tick()
    conn.execute(text("UPDATE user_words SET updated_hlc = :h WHERE lexeme_id = :id"), {"h": stamp, "id": lexeme_id})
    return stamp


def ensure_lexeme(conn: Connection, lang: str, lemma: str, reading: str, pos: str = "", rank: int | None = None) -> int:
    conn.execute(
        text(
            "INSERT OR IGNORE INTO lexemes (language_code, lemma, reading, pos, freq_rank, is_proper) "
            "VALUES (:l, :lemma, :r, :pos, :rank, :proper)"
        ),
        {"l": lang, "lemma": lemma, "r": reading, "pos": pos, "rank": rank, "proper": int(pos == "PROPN")},
    )
    return conn.execute(
        text("SELECT id FROM lexemes WHERE language_code = :l AND lemma = :lemma AND reading = :r"),
        {"l": lang, "lemma": lemma, "r": reading},
    ).scalar_one()


def states(conn: Connection, lang: str, keys: list[tuple[str, str]]) -> dict[str, dict[str, Any]]:
    """Current state for (lemma, reading) pairs that have a user_words row."""
    lemmas = list({lemma for lemma, _ in keys})
    if not lemmas:
        return {}
    rows = conn.execute(
        text(
            "SELECT l.id, l.lemma, l.reading, w.status, w.p_known, w.saved, w.lookups FROM lexemes l "
            "JOIN user_words w ON w.lexeme_id = l.id WHERE l.language_code = :l AND l.lemma IN :lemmas"
        ).bindparams(bindparam("lemmas", expanding=True)),
        {"l": lang, "lemmas": lemmas},
    ).all()
    return {
        lexeme_key(r[1], r[2]): {"lexeme_id": r[0], "status": r[3], "p_known": r[4], "saved": bool(r[5]), "lookups": r[6]}
        for r in rows
    }


def _event(conn: Connection, lexeme_id: int, event: str, value: str | None = None, *, at: str | None = None,
           content_item_id: int | None = None) -> None:
    conn.execute(
        text(
            "INSERT INTO word_events (lexeme_id, event, value, content_item_id, created_at) "
            "VALUES (:id, :e, :v, (SELECT id FROM content_items WHERE id = :c), COALESCE(:at, strftime('%Y-%m-%dT%H:%M:%fZ','now')))"
        ),
        {"id": lexeme_id, "e": event, "v": value, "c": content_item_id, "at": at},
    )


def record_lookup(
    conn: Connection, lang: str, lemma: str, reading: str, pos: str, rank: int | None, model_p: float,
    *, at: str | None = None, content_item_id: int | None = None,
) -> dict[str, Any]:
    """A lookup is evidence you don't (fully) know the word: lower its probability.

    `at` is when it happened (a lookup made offline on the phone arrives later) and `content_item_id` where: the
    memory model and the recommender use both."""
    lexeme_id = ensure_lexeme(conn, lang, lemma, reading, pos, rank)
    now = at or to_iso(utc_now())
    row = conn.execute(text("SELECT status, p_known FROM user_words WHERE lexeme_id = :id"), {"id": lexeme_id}).first()
    if row is None:
        conn.execute(
            text(
                "INSERT INTO user_words (lexeme_id, status, p_known, lookups, first_seen_at, last_seen_at, "
                "last_lookup_at, updated_hlc) VALUES (:id, 'seen', :p, 1, :now, :now, :now, NULL)"
            ),
            {"id": lexeme_id, "p": round(min(model_p, 0.3), 4), "now": now},
        )
    else:
        status, p = row
        # A lookup never raises the probability; it shrinks it, bottoming out near zero.
        new_p = p if status == "ignored" else max(min(p, 0.02), p * 0.6)
        conn.execute(
            text(
                "UPDATE user_words SET lookups = lookups + 1, p_known = :p, last_lookup_at = :now, last_seen_at = :now "
                "WHERE lexeme_id = :id"
            ),
            {"p": round(new_p, 4), "now": now, "id": lexeme_id},
        )
    _event(conn, lexeme_id, "lookup", at=at, content_item_id=content_item_id)
    return word_state(conn, lexeme_id)


def set_status(
    conn: Connection,
    lang: str,
    lemma: str,
    reading: str,
    status: str,
    *,
    pos: str = "",
    rank: int | None = None,
    save: bool = False,
    context: dict[str, Any] | None = None,
    event: str = "status_change",
    note: str | None = None,
) -> dict[str, Any]:
    """Set a word's status. `note` is kept with the event (e.g. "phone" for a change made on the phone)."""
    if status not in STATUSES:
        raise VocabError(f"unknown status '{status}'")
    lexeme_id = ensure_lexeme(conn, lang, lemma, reading, pos, rank)
    now = to_iso(utc_now())
    p = STATUS_P.get(status, 0.1)
    conn.execute(
        text(
            "INSERT INTO user_words (lexeme_id, status, p_known, saved, first_seen_at, last_seen_at, status_changed_at) "
            "VALUES (:id, :s, :p, :saved, :now, :now, :now) ON CONFLICT(lexeme_id) DO UPDATE SET "
            "status = excluded.status, p_known = excluded.p_known, saved = MAX(user_words.saved, excluded.saved), "
            "last_seen_at = excluded.last_seen_at, status_changed_at = excluded.status_changed_at"
        ),
        {"id": lexeme_id, "s": status, "p": p, "saved": int(save), "now": now},
    )
    _event(conn, lexeme_id, "save" if save else event, f"{status} ({note})" if note else status)
    stamp_hlc(conn, lexeme_id)
    if context and context.get("sentence"):
        add_context(conn, lexeme_id, context)
    return word_state(conn, lexeme_id)


def add_context(conn: Connection, lexeme_id: int, context: dict[str, Any]) -> None:
    sentence = str(context["sentence"]).strip()[:1000]
    exists = conn.execute(
        text("SELECT 1 FROM word_contexts WHERE lexeme_id = :id AND sentence = :s"), {"id": lexeme_id, "s": sentence}
    ).first()
    if exists:
        return
    conn.execute(
        text(
            "INSERT INTO word_contexts (lexeme_id, content_item_id, surface, sentence, locator) "
            "VALUES (:id, :item, :surface, :sentence, :locator)"
        ),
        {
            "id": lexeme_id,
            "item": context.get("content_item_id"),
            "surface": str(context.get("surface") or "")[:100],
            "sentence": sentence,
            "locator": context.get("locator"),
        },
    )


def word_state(conn: Connection, lexeme_id: int) -> dict[str, Any]:
    row = conn.execute(
        text(
            "SELECT l.id, l.language_code, l.lemma, l.reading, l.pos, l.freq_rank, w.status, w.p_known, w.saved, "
            "w.lookups, w.user_gloss, w.user_note, w.first_seen_at, w.last_seen_at, "
            "(SELECT COUNT(*) FROM word_contexts c WHERE c.lexeme_id = l.id) "
            "FROM lexemes l LEFT JOIN user_words w ON w.lexeme_id = l.id WHERE l.id = :id"
        ),
        {"id": lexeme_id},
    ).first()
    if not row:
        raise VocabError("no such word")
    keys = (
        "lexeme_id", "language", "lemma", "reading", "pos", "rank", "status", "p_known", "saved", "lookups",
        "user_gloss", "user_note", "first_seen_at", "last_seen_at", "contexts",
    )
    state = dict(zip(keys, row))
    state["saved"] = bool(state["saved"])
    return state


def contexts(conn: Connection, lexeme_id: int, limit: int = 20) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            "SELECT id, surface, sentence, locator, created_at FROM word_contexts WHERE lexeme_id = :id "
            "ORDER BY created_at DESC LIMIT :limit"
        ),
        {"id": lexeme_id, "limit": limit},
    ).all()
    return [dict(zip(("id", "surface", "sentence", "locator", "created_at"), r)) for r in rows]


def list_words(
    conn: Connection, lang: str, *, status: str | None = None, q: str | None = None, limit: int = 50, offset: int = 0
) -> dict[str, Any]:
    where = ["l.language_code = :l"]
    params: dict[str, Any] = {"l": lang, "limit": limit, "offset": offset}
    if status == "saved":
        where.append("w.saved = 1")
    elif status:
        where.append("w.status = :status")
        params["status"] = status
    if q:
        where.append("(l.lemma LIKE :q OR l.reading LIKE :q OR w.user_gloss LIKE :q OR w.user_note LIKE :q)")
        params["q"] = f"%{q}%"
    clause = " AND ".join(where)
    total = conn.execute(
        text(f"SELECT COUNT(*) FROM user_words w JOIN lexemes l ON l.id = w.lexeme_id WHERE {clause}"), params
    ).scalar_one()
    rows = conn.execute(
        text(
            "SELECT l.id, l.lemma, l.reading, l.pos, l.freq_rank, w.status, w.p_known, w.saved, w.lookups, "
            "w.user_gloss, w.last_seen_at, (SELECT COUNT(*) FROM word_contexts c WHERE c.lexeme_id = l.id), "
            "(SELECT sentence FROM word_contexts c WHERE c.lexeme_id = l.id ORDER BY c.created_at DESC LIMIT 1) "
            f"FROM user_words w JOIN lexemes l ON l.id = w.lexeme_id WHERE {clause} "
            "ORDER BY COALESCE(w.status_changed_at, w.last_seen_at) DESC, l.id DESC LIMIT :limit OFFSET :offset"
        ),
        params,
    ).all()
    keys = (
        "lexeme_id", "lemma", "reading", "pos", "rank", "status", "p_known", "saved", "lookups", "user_gloss",
        "last_seen_at", "contexts", "latest_sentence",
    )
    items = []
    for row in rows:
        item = dict(zip(keys, row))
        item["saved"] = bool(item["saved"])
        items.append(item)
    return {"total": total, "items": items}


def update_word(conn: Connection, lexeme_id: int, *, status: str | None = None, note: str | None = None, gloss: str | None = None) -> dict[str, Any]:
    state = word_state(conn, lexeme_id)
    if status is not None:
        set_status(conn, state["language"], state["lemma"], state["reading"], status)
    if note is not None or gloss is not None:
        conn.execute(
            text(
                "UPDATE user_words SET user_note = COALESCE(:note, user_note), user_gloss = COALESCE(:gloss, user_gloss) "
                "WHERE lexeme_id = :id"
            ),
            {"note": note, "gloss": gloss, "id": lexeme_id},
        )
    return word_state(conn, lexeme_id)


def summary(conn: Connection, lang: str) -> dict[str, int]:
    rows = conn.execute(
        text(
            "SELECT w.status, COUNT(*) FROM user_words w JOIN lexemes l ON l.id = w.lexeme_id "
            "WHERE l.language_code = :l GROUP BY w.status"
        ),
        {"l": lang},
    ).all()
    counts = {status: 0 for status in STATUSES}
    counts.update({status: n for status, n in rows})
    counts["saved"] = conn.execute(
        text("SELECT COUNT(*) FROM user_words w JOIN lexemes l ON l.id = w.lexeme_id WHERE l.language_code = :l AND w.saved = 1"),
        {"l": lang},
    ).scalar_one()
    return counts


def as_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)
