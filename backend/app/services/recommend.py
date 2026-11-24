"""What to watch and read next: matched to your level and your taste, never something you've already watched.

score = level fit × (1 + 0.15·min(re-encounters, 4)) × freshness × confidence × taste
  level fit      how close the item is to your "just right" coverage (calibrated by your difficulty ratings)
  re-encounters  how many of your 'learning' words appear in it (no flashcards: words come back here)
  freshness      unfinished books and manga you started get a boost
  confidence     measured items count fully; items whose level is estimated from their channel count a little less
  taste          what you tend to finish, come back to or dismiss: channels, sites, topics, length (services/taste.py)
Never suggested: videos you've watched (tracked in the app or imported from the Immersion Tracker CSVs) and anything
you've finished, dismissed or archived.

Two views of the same ranking:
  up_next  a short mixed list (Today): at most 4 of one kind, at most 2 per creator, one stretch and one comfortable
           pick if any exist.
  feed     one shelf (videos, or things to read) as a long, paged list for infinite scrolling. Creators are spread
           out so one channel never fills a screen.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from typing import Any

from sqlalchemy import Connection, text

from app.services import taste
from app.services.catalog import CONFIDENCE
from app.services.content import MANGA_TYPES, READ_TYPES, SHELVES, WATCH_TYPES

WATCHED_TYPES = ", ".join(f"'{t}'" for t in WATCH_TYPES)

KIND_LIMIT, CREATOR_LIMIT = 4, 2
CREATOR_GAP = 3  # in a feed, the same creator appears at most once in any 3 neighbouring places when possible
RANK_CACHE_SECONDS = 90.0

_KEYS = (
    "id", "type", "title", "creator", "source", "external_id", "url", "duration_sec", "word_count", "status",
    "progress", "origin", "metadata", "coverage", "i1_score", "band", "expected_unknown", "estimated", "learning_words",
    "watched",
)


def candidates(conn: Connection, lang: str, shelf: str | None = None) -> list[dict[str, Any]]:
    """Everything that may be suggested, with its score inputs. `shelf` limits it to 'watch', 'read' or 'manga'."""
    types = SHELVES.get(shelf) if shelf else WATCH_TYPES + READ_TYPES + MANGA_TYPES
    type_list = ", ".join(f"'{t}'" for t in types or ())
    rows = conn.execute(
        text(
            "SELECT ci.id, ci.type, ci.title, ci.creator, ci.source, ci.external_id, ci.source_url, ci.duration_sec, "
            "ci.word_count, ci.status, ci.progress, ci.origin, ci.metadata_json, cs.coverage, cs.i1_score, cs.band, "
            "cs.expected_unknown, cs.estimated, "
            "CASE WHEN cs.estimated = 1 THEN 0 ELSE (SELECT COUNT(*) FROM content_lemmas cl JOIN user_words w "
            " ON w.lexeme_id = cl.lexeme_id WHERE cl.content_item_id = ci.id AND w.status = 'learning') END AS learning_words, "
            "(SELECT COUNT(*) FROM activity_sessions s WHERE s.content_item_id = ci.id AND s.is_baseline = 0) AS watched "
            "FROM content_items ci JOIN content_scores cs ON cs.content_item_id = ci.id "
            f"WHERE ci.language_code = :l AND ci.type IN ({type_list}) "
            "AND ci.status NOT IN ('dismissed', 'archived', 'finished') "
            "AND (ci.analysis_status = 'done' OR cs.estimated = 1) "
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
        item["estimated"] = bool(item["estimated"])
        item["level_basis"] = meta.get("level_basis") if item["estimated"] else None
        out.append(item)
    return out


def kind_of(item: dict[str, Any]) -> str:
    if item["type"] in MANGA_TYPES:
        return "manga"
    return "reading" if item["type"] in READ_TYPES else "video"


def _base(item: dict[str, Any]) -> float:
    fit = item["i1_score"] or 0.0
    reencounter = 1 + 0.15 * min(item["learning_words"], 4)
    freshness = 1.25 if item["status"] == "in_progress" and (item["progress"] or 0) < 0.9 else 1.0
    confidence = CONFIDENCE.get(item["level_basis"] or "", 0.8) if item["estimated"] else 1.0
    return fit * reencounter * freshness * confidence


def _score(item: dict[str, Any]) -> float:
    return item.get("_score", _base(item))


def _reasons(item: dict[str, Any]) -> list[str]:
    reasons = [f"≈ {round((item['coverage'] or 0) * 100)}% known"]
    if item["status"] == "in_progress" and (item["progress"] or 0) < 0.9:
        reasons.append("continue where you left off")
    reasons += item.get("_taste_reasons", [])
    if item["learning_words"]:
        reasons.append(f"brings back {item['learning_words']} of your saved words")
    if item["estimated"]:
        reasons.append("level estimated from the channel" if item["level_basis"] != "label" else "level estimated from the channel's label")
    return reasons


def _present(item: dict[str, Any]) -> dict[str, Any]:
    clean = {k: v for k, v in item.items() if not k.startswith("_")}
    return {**clean, "kind": kind_of(item), "score": round(_score(item), 4), "reasons": _reasons(item)}


def _apply_taste(conn: Connection, lang: str, items: list[dict[str, Any]]) -> None:
    prof = taste.profile(conn, lang)
    measured = [i["id"] for i in items if not i["estimated"] and i["type"] not in MANGA_TYPES]
    vecs = taste.item_vectors(conn, measured, prof.idf) if prof.topics else {}
    for item in items:
        factor, reasons = prof.multiplier(item, vecs.get(item["id"]))
        item["_score"] = _base(item) * factor
        item["_taste"] = round(factor, 3)
        item["_taste_reasons"] = reasons


def spread_creators(items: list[dict[str, Any]], gap: int = CREATOR_GAP) -> list[dict[str, Any]]:
    """Keep the ranking, but don't let one creator take neighbouring places while others are waiting."""
    remaining = list(items)
    out: list[dict[str, Any]] = []
    while remaining:
        recent = {i["creator"] for i in out[-(gap - 1):] if i["creator"]} if gap > 1 else set()
        index = next((n for n, i in enumerate(remaining) if not i["creator"] or i["creator"] not in recent), 0)
        out.append(remaining.pop(index))
    return out


# ranked lists are cached briefly, so the pages of an infinite scroll come from the same order
_RANKED: dict[tuple[str, str], tuple[float, tuple, list[dict[str, Any]]]] = {}


def _version(conn: Connection, lang: str) -> tuple:
    return tuple(
        conn.execute(
            text(
                "SELECT (SELECT MAX(id) FROM content_items), (SELECT COUNT(*) FROM content_items WHERE language_code = :l "
                "AND status IN ('dismissed', 'finished')), (SELECT MAX(computed_at) FROM content_scores), "
                "(SELECT MAX(id) FROM activity_sessions), (SELECT value_json FROM app_settings WHERE key = :k)"
            ),
            {"l": lang, "k": f"calibration.{lang}.listening"},
        ).first()
        or ()
    )


def ranked(conn: Connection, lang: str, shelf: str | None) -> list[dict[str, Any]]:
    """Every suggestion for a shelf (None = all), best first, creators spread out."""
    key = (lang, shelf or "all")
    version = _version(conn, lang)
    cached = _RANKED.get(key)
    if cached and cached[1] == version and time.monotonic() - cached[0] < RANK_CACHE_SECONDS:
        return cached[2]
    items = candidates(conn, lang, shelf)
    _apply_taste(conn, lang, items)
    items.sort(key=lambda i: (-_score(i), i["id"]))
    result = spread_creators(items)
    _RANKED[key] = (time.monotonic(), version, result)
    return result


def invalidate() -> None:
    _RANKED.clear()


def up_next(conn: Connection, lang: str, n: int = 12) -> dict[str, Any]:
    pool = sorted(ranked(conn, lang, None), key=_score, reverse=True)
    # Prefer measured items for the short list; estimated ones fill in only if needed.
    pool.sort(key=lambda i: (i["estimated"], -_score(i)))
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
        match = next((i for i in pool if i["band"] == band and not i["estimated"] and i not in picks), None)
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


def feed(conn: Connection, lang: str, shelf: str, offset: int = 0, limit: int = 24) -> dict[str, Any]:
    """One shelf's suggestions, best first, paged. The order is stable between pages while nothing changes."""
    ordered = ranked(conn, lang, shelf)
    page = ordered[offset : offset + limit]
    end = offset + len(page)
    return {
        "language": lang,
        "shelf": shelf,
        "total": len(ordered),
        "estimated": sum(1 for i in ordered if i["estimated"]),
        "items": [_present(item) for item in page],
        "next_offset": end if end < len(ordered) else None,
    }


def pool_size(conn: Connection, lang: str, shelf: str) -> int:
    return len(ranked(conn, lang, shelf))
