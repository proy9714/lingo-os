"""What to watch and read next: matched to your level, never something you've already watched (ARCHITECTURE §6.3).

score = i+1 fit × (1 + 0.15·min(re-encounters, 4)) × freshness
  re-encounters: how many of your 'learning' words appear in the item (no flashcards: words come back here)
  freshness: unfinished books and manga you started get a boost
Never suggested: videos you've watched (tracked in the app or imported from the Immersion Tracker CSVs) and
anything you've finished, dismissed or archived.

Two views of the same ranking:
  up_next  a short mixed list (Today): at most 4 of one kind, at most 2 per creator, one stretch and one comfortable
           pick if any exist.
  feed     one shelf (videos, or things to read) as a long, paged list for infinite scrolling. Creators are spread
           out so one channel never fills a screen.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from sqlalchemy import Connection, text

from app.services.content import MANGA_TYPES, READ_TYPES, SHELVES, WATCH_TYPES

WATCHED_TYPES = ", ".join(f"'{t}'" for t in WATCH_TYPES)

KIND_LIMIT, CREATOR_LIMIT = 4, 2
CREATOR_GAP = 3  # in a feed, the same creator appears at most once in any 3 neighbouring places when possible

_KEYS = (
    "id", "type", "title", "creator", "source", "external_id", "url", "duration_sec", "word_count", "status",
    "progress", "origin", "metadata", "coverage", "i1_score", "band", "expected_unknown", "learning_words", "watched",
)


def candidates(conn: Connection, lang: str, shelf: str | None = None) -> list[dict[str, Any]]:
    """Everything that may be suggested, with its score inputs. `shelf` limits it to 'watch', 'read' or 'manga'."""
    types = SHELVES.get(shelf) if shelf else WATCH_TYPES + READ_TYPES + MANGA_TYPES
    type_list = ", ".join(f"'{t}'" for t in types or ())
    rows = conn.execute(
        text(
            "SELECT ci.id, ci.type, ci.title, ci.creator, ci.source, ci.external_id, ci.source_url, ci.duration_sec, "
            "ci.word_count, ci.status, ci.progress, ci.origin, ci.metadata_json, cs.coverage, cs.i1_score, cs.band, "
            "cs.expected_unknown, "
            "(SELECT COUNT(*) FROM content_lemmas cl JOIN user_words w ON w.lexeme_id = cl.lexeme_id "
            " WHERE cl.content_item_id = ci.id AND w.status = 'learning') AS learning_words, "
            "(SELECT COUNT(*) FROM activity_sessions s WHERE s.content_item_id = ci.id AND s.is_baseline = 0) AS watched "
            "FROM content_items ci JOIN content_scores cs ON cs.content_item_id = ci.id "
            f"WHERE ci.language_code = :l AND ci.type IN ({type_list}) "
            "AND ci.status NOT IN ('dismissed', 'archived', 'finished') AND ci.analysis_status = 'done' "
            f"AND NOT (ci.type IN ({WATCHED_TYPES}) AND EXISTS (SELECT 1 FROM activity_sessions w WHERE w.content_item_id = ci.id))"
        ),
        {"l": lang},
    ).all()
    out = []
    for row in rows:
        item = dict(zip(_KEYS, row))
        meta = json.loads(item.pop("metadata") or "{}")
        item["image"] = meta.get("image")
        item["site"] = meta.get("site")
        out.append(item)
    return out


def kind_of(item: dict[str, Any]) -> str:
    if item["type"] in MANGA_TYPES:
        return "manga"
    return "reading" if item["type"] in READ_TYPES else "video"


def _score(item: dict[str, Any]) -> float:
    fit = item["i1_score"] or 0.0
    reencounter = 1 + 0.15 * min(item["learning_words"], 4)
    freshness = 1.25 if item["status"] == "in_progress" and (item["progress"] or 0) < 0.9 else 1.0
    return fit * reencounter * freshness


def _reasons(item: dict[str, Any]) -> list[str]:
    reasons = [f"≈ {round((item['coverage'] or 0) * 100)}% known"]
    if item["learning_words"]:
        reasons.append(f"brings back {item['learning_words']} of your saved words")
    if item["status"] == "in_progress" and (item["progress"] or 0) < 0.9:
        reasons.append("continue where you left off")
    return reasons


def _present(item: dict[str, Any]) -> dict[str, Any]:
    return {**item, "kind": kind_of(item), "score": round(_score(item), 4), "reasons": _reasons(item)}


def up_next(conn: Connection, lang: str, n: int = 12) -> dict[str, Any]:
    pool = sorted(candidates(conn, lang), key=_score, reverse=True)
    picks: list[dict[str, Any]] = []
    kinds: Counter[str] = Counter()
    creators: Counter[str] = Counter()

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
    return {"language": lang, "available": len(pool), "picks": [_present(item) for item in picks[:n]]}


def spread_creators(items: list[dict[str, Any]], gap: int = CREATOR_GAP) -> list[dict[str, Any]]:
    """Keep the ranking, but don't let one creator take neighbouring places while others are waiting."""
    remaining = list(items)
    out: list[dict[str, Any]] = []
    while remaining:
        recent = {i["creator"] for i in out[-(gap - 1):] if i["creator"]} if gap > 1 else set()
        index = next((n for n, i in enumerate(remaining) if not i["creator"] or i["creator"] not in recent), 0)
        out.append(remaining.pop(index))
    return out


def feed(conn: Connection, lang: str, shelf: str, offset: int = 0, limit: int = 24) -> dict[str, Any]:
    """One shelf's suggestions, best first, paged. The order is stable between pages while nothing changes."""
    ranked = sorted(candidates(conn, lang, shelf), key=lambda i: (-_score(i), i["id"]))
    ordered = spread_creators(ranked)
    page = ordered[offset : offset + limit]
    end = offset + len(page)
    return {
        "language": lang,
        "shelf": shelf,
        "total": len(ordered),
        "items": [_present(item) for item in page],
        "next_offset": end if end < len(ordered) else None,
    }


def pool_size(conn: Connection, lang: str, shelf: str) -> int:
    return len(candidates(conn, lang, shelf))
