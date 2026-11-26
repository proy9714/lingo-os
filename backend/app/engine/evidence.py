"""Layer 2 of the level estimate (ARCHITECTURE §6.11): what the videos you watched actually contained."""

from __future__ import annotations

import math
from typing import Any

from sqlalchemy import Connection, bindparam, text

# How many times you went through each item: every session counts the share of the item it covered (60 seconds of a
# 40-minute video is 1/40 of a watch, not a whole one), so words "heard" follow what you actually heard or read.
# Reading length is estimated at 150 words a minute; an item of unknown length counts a session as 10 minutes.
WATCHES = (
    "SELECT s.content_item_id, SUM(MIN(1.0, s.active_seconds * 1.0 / COALESCE(NULLIF(ci.duration_sec, 0), "
    "NULLIF(ci.word_count, 0) * 0.4, 600))) AS watches, SUM(s.active_seconds) AS seconds FROM activity_sessions s "
    "JOIN content_items ci ON ci.id = s.content_item_id WHERE s.is_baseline = 0 GROUP BY s.content_item_id"
)
COVERAGE_TARGET = 0.90


def heard_for(conn: Connection, lang: str, lemmas: list[str]) -> dict[tuple[str, str], int]:
    """How many times each (lemma, reading) was heard across everything you watched."""
    if not lemmas:
        return {}
    rows = conn.execute(
        text(
            f"SELECT l.lemma, l.reading, SUM(cl.count * w.watches) FROM lexemes l JOIN content_lemmas cl ON cl.lexeme_id = l.id "
            f"JOIN ({WATCHES}) w ON w.content_item_id = cl.content_item_id "
            "WHERE l.language_code = :l AND l.lemma IN :lemmas GROUP BY l.id"
        ).bindparams(bindparam("lemmas", expanding=True)),
        {"l": lang, "lemmas": list(set(lemmas))},
    ).all()
    return {(lemma, reading): int(heard) for lemma, reading, heard in rows}


def sample_running_words(conn: Connection, item_id: int) -> int:
    """Running words in the analysed text. For a sampled book this is the sample, matching content_lemmas."""
    row = conn.execute(
        text(
            "SELECT ci.word_count, COALESCE(ca.sample_ratio, 1) FROM content_items ci "
            "LEFT JOIN content_analysis ca ON ca.content_item_id = ci.id WHERE ci.id = :id"
        ),
        {"id": item_id},
    ).first()
    if not row or not row[0]:
        return 0
    return int(round(row[0] * min(1.0, row[1] or 1.0)))


def vocabulary_for_coverage(conn: Connection, item_id: int, target: float = COVERAGE_TARGET) -> int | None:
    """Smallest N such that knowing the N most frequent words covers `target` of this item's running words.

    Function words, names and numbers count as covered, the same rule the item scores use.
    """
    rows = conn.execute(
        text(
            "SELECT COALESCE(l.freq_rank, 100000), cl.count FROM content_lemmas cl JOIN lexemes l ON l.id = cl.lexeme_id "
            "WHERE cl.content_item_id = :id ORDER BY 1"
        ),
        {"id": item_id},
    ).all()
    content = sum(count for _, count in rows)
    if content < 50:
        return None
    others = max(0, sample_running_words(conn, item_id) - content)
    total = content + others
    covered = others
    if covered / total >= target:
        return 0
    for rank, count in rows:
        covered += count
        if covered / total >= target:
            return int(rank)
    return None


def content_evidence(conn: Connection, lang: str) -> dict[str, Any]:
    watched = conn.execute(
        text(
            f"SELECT ci.id, w.watches, w.seconds, ca.token_count FROM content_items ci JOIN ({WATCHES}) w "
            "ON w.content_item_id = ci.id LEFT JOIN content_analysis ca ON ca.content_item_id = ci.id "
            "WHERE ci.language_code = :l"
        ),
        {"l": lang},
    ).all()
    analysed = [r for r in watched if r[3]]
    heard_rows = conn.execute(
        text(
            f"SELECT SUM(cl.count * w.watches) AS heard FROM content_lemmas cl JOIN ({WATCHES}) w "
            "ON w.content_item_id = cl.content_item_id JOIN lexemes l ON l.id = cl.lexeme_id "
            "WHERE l.language_code = :l GROUP BY cl.lexeme_id"
        ),
        {"l": lang},
    ).all()
    heard = [int(r[0]) for r in heard_rows]

    needs = []
    for item_id, _watches, seconds, _tokens in analysed:
        n = vocabulary_for_coverage(conn, item_id)
        if n:
            needs.append((n, seconds or 0))
    typical_need = _weighted_median(needs)
    return {
        "videos_watched": len(watched),
        "videos_analysed": len(analysed),
        "content_words_heard": int(sum(r[3] * r[1] for r in analysed)),
        "lemmas_heard": len(heard),
        "lemmas_heard_10_plus": sum(1 for h in heard if h >= 10),
        "lemmas_heard_3_to_9": sum(1 for h in heard if 3 <= h < 10),
        "vocabulary_for_90_percent": typical_need,
        "coverage_target": COVERAGE_TARGET,
    }


def _weighted_median(values: list[tuple[int, float]]) -> int | None:
    if not values:
        return None
    values.sort()
    total = sum(w or 1 for _, w in values)
    running = 0.0
    for value, weight in values:
        running += weight or 1
        if running >= total / 2:
            return value
    return values[-1][0]


def blend_with_hours(hours_words: float, evidence: dict[str, Any]) -> tuple[float, float]:
    """Combine the hours prior with what your content needed. Returns (words, confidence)."""
    need = evidence.get("vocabulary_for_90_percent")
    analysed = evidence.get("videos_analysed", 0)
    if not need or analysed < 10:
        return hours_words, 0.2
    weight = min(0.6, analysed / 250)  # content you watch with on-screen subtitles is an upper-bound signal
    words = math.exp((1 - weight) * math.log(hours_words) + weight * math.log(need))
    return words, round(0.2 + 0.15 * weight / 0.6, 3)
