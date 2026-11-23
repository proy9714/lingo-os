"""Up Next: at least 10 picks matched to your level, with variety rules (ARCHITECTURE §6.3).

score = i+1 fit × (1 + 0.15·min(re-encounters, 4)) × freshness
  re-encounters: how many of your 'learning' words appear in the item (no flashcards: words come back here)
  freshness: unfinished in-progress items get a boost; finished ones are re-watch suggestions at half weight
Diversity: at most 4 of one kind (video / reading), at most 2 per creator; one stretch and one comfortable pick if any exist.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import Connection, text

from app.services.content import MANGA_TYPES, READ_TYPES

KIND_LIMIT, CREATOR_LIMIT = 4, 2


def candidates(conn: Connection, lang: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            "SELECT ci.id, ci.type, ci.title, ci.creator, ci.source, ci.external_id, ci.duration_sec, ci.word_count, ci.status, "
            "ci.progress, cs.coverage, cs.i1_score, cs.band, cs.expected_unknown, "
            "(SELECT COUNT(*) FROM content_lemmas cl JOIN user_words w ON w.lexeme_id = cl.lexeme_id "
            " WHERE cl.content_item_id = ci.id AND w.status = 'learning') AS learning_words, "
            "(SELECT COUNT(*) FROM activity_sessions s WHERE s.content_item_id = ci.id AND s.is_baseline = 0) AS watched "
            "FROM content_items ci JOIN content_scores cs ON cs.content_item_id = ci.id "
            "WHERE ci.language_code = :l AND ci.status NOT IN ('dismissed', 'archived') AND ci.analysis_status = 'done'"
        ),
        {"l": lang},
    ).all()
    keys = (
        "id", "type", "title", "creator", "source", "external_id", "duration_sec", "word_count", "status", "progress",
        "coverage", "i1_score", "band", "expected_unknown", "learning_words", "watched",
    )
    return [dict(zip(keys, row)) for row in rows]


def _score(item: dict[str, Any]) -> float:
    fit = item["i1_score"] or 0.0
    reencounter = 1 + 0.15 * min(item["learning_words"], 4)
    if item["status"] == "in_progress" and (item["progress"] or 0) < 0.9:
        freshness = 1.25
    elif item["status"] == "finished" or item["watched"]:
        freshness = 0.5
    else:
        freshness = 1.0
    return fit * reencounter * freshness


def _reasons(item: dict[str, Any]) -> list[str]:
    reasons = [f"≈ {round((item['coverage'] or 0) * 100)}% known"]
    if item["learning_words"]:
        reasons.append(f"brings back {item['learning_words']} of your saved words")
    if item["status"] == "in_progress" and (item["progress"] or 0) < 0.9:
        reasons.append("continue where you left off")
    elif item["watched"]:
        reasons.append("a re-watch: easier the second time")
    return reasons


def up_next(conn: Connection, lang: str, n: int = 12) -> dict[str, Any]:
    pool = sorted(candidates(conn, lang), key=_score, reverse=True)
    picks: list[dict[str, Any]] = []
    kinds: Counter[str] = Counter()
    creators: Counter[str] = Counter()

    def kind_of(item: dict[str, Any]) -> str:
        if item["type"] in MANGA_TYPES:
            return "manga"
        return "reading" if item["type"] in READ_TYPES else "video"

    def take(item: dict[str, Any]) -> None:
        picks.append(item)
        kinds[kind_of(item)] += 1
        if item["creator"]:
            creators[item["creator"]] += 1

    # One stretch and one comfortable pick first, if they exist.
    for band in ("stretch", "comfortable"):
        match = next((i for i in pool if i["band"] == band and i not in picks), None)
        if match:
            take(match)
    # Variety rules first; if they leave too few picks, loosen them a step at a time so a library that is mostly
    # one channel still mixes in everything else before repeating that channel.
    for kind_cap, creator_cap in ((KIND_LIMIT, CREATOR_LIMIT), (n, 3), (n, 4), (n, 6), (n, n)):
        for item in pool:
            if len(picks) >= n:
                break
            if item in picks:
                continue
            if kinds[kind_of(item)] >= kind_cap or (item["creator"] and creators[item["creator"]] >= creator_cap):
                continue
            take(item)
    picks.sort(key=_score, reverse=True)
    return {
        "language": lang,
        "available": len(pool),
        "picks": [{**item, "kind": kind_of(item), "score": round(_score(item), 4), "reasons": _reasons(item)} for item in picks[:n]],
    }
