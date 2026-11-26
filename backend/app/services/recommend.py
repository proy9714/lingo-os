"""What to watch and read next: matched to your level and your taste, never something you've already watched.

score = level fit × freshness × confidence × taste × what it teaches
  level fit      how close the item is to your "just right" coverage (calibrated by your difficulty ratings)
  freshness      unfinished books and manga you started get a boost
  confidence     measured items count fully; items whose level is estimated from their channel count a little less
  taste          what you tend to finish, come back to or dismiss: channels (sampled, so new ones get tried), sites,
                 topics, length (services/taste.py)
  what it teaches  common new words, learning words due to come back, speech speed, cards you keep passing by
                 (services/ranker.py)
The best of the list is then re-ranked for variety (channel, topic, length, kind), and Today prefers what fits the
minutes left in your daily goal.
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

from app.services import content, ranker, taste
from app.services.catalog import CONFIDENCE
from app.services.content import MANGA_TYPES, PODCAST_TYPES, READ_TYPES, SHELVES, WATCH_TYPES

WATCHED_TYPES = ", ".join(f"'{t}'" for t in WATCH_TYPES)

KIND_LIMIT, CREATOR_LIMIT = 4, 2
CREATOR_GAP = 3  # in a feed, the same creator appears at most once in any 3 neighbouring places when possible
RANK_CACHE_SECONDS = 90.0

_KEYS = (
    "id", "type", "title", "creator", "source", "external_id", "url", "duration_sec", "word_count", "status",
    "progress", "origin", "metadata", "coverage", "i1_score", "band", "expected_unknown", "estimated", "learning_words",
    "watched", "speech_wpm",
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
            "(SELECT COUNT(*) FROM activity_sessions s WHERE s.content_item_id = ci.id AND s.is_baseline = 0) AS watched, "
            "ca.speech_wpm "
            "FROM content_items ci JOIN content_scores cs ON cs.content_item_id = ci.id "
            "LEFT JOIN content_analysis ca ON ca.content_item_id = ci.id "
            f"WHERE ci.language_code = :l AND ci.type IN ({type_list}) "
            "AND ci.status NOT IN ('dismissed', 'archived', 'finished') "
            "AND (ci.analysis_status = 'done' OR cs.estimated = 1) "
            f"AND NOT (ci.type IN ({WATCHED_TYPES}) AND {content.WATCHED_SQL})"
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
        item["kind"] = kind_of(item)
        out.append(item)
    return out


def kind_of(item: dict[str, Any]) -> str:
    if item["type"] in MANGA_TYPES:
        return "manga"
    if item["type"] in PODCAST_TYPES:
        return "podcast"
    return "reading" if item["type"] in READ_TYPES else "video"


def _base(item: dict[str, Any]) -> float:
    fit = item["i1_score"] or 0.0
    freshness = 1.25 if item["status"] == "in_progress" and (item["progress"] or 0) < 0.9 else 1.0
    confidence = CONFIDENCE.get(item["level_basis"] or "", 0.8) if item["estimated"] else 1.0
    return fit * freshness * confidence


def _score(item: dict[str, Any]) -> float:
    return item.get("_score", _base(item))


def _reasons(item: dict[str, Any]) -> list[str]:
    reasons = [f"≈ {round((item['coverage'] or 0) * 100)}% known"]
    if item["status"] == "in_progress" and (item["progress"] or 0) < 0.9:
        reasons.append("continue where you left off")
    reasons += item.get("_taste_reasons", [])
    due = item.get("_due_words", 0)
    if due:
        reasons.append(f"brings back {due} {'word' if due == 1 else 'words'} you're learning, due again")
    elif item["learning_words"]:
        reasons.append(f"brings back {item['learning_words']} of your saved words")
    if item.get("_teach") is not None and item["_teach"] >= 0.6:
        reasons.append("its new words are common, useful ones")
    if item.get("_time_fit"):
        reasons.append("fits the time left in today's goal")
    if item.get("_fill"):
        reasons.append("the closest to your level found so far")
    if item["estimated"]:
        reasons.append({"label": "level estimated from the channel's label", "language": "a learner channel, level not measured yet"}
                       .get(item["level_basis"] or "", "level estimated from the channel"))
    return reasons


def _present(item: dict[str, Any]) -> dict[str, Any]:
    clean = {k: v for k, v in item.items() if not k.startswith("_")}
    return {**clean, "kind": kind_of(item), "score": round(_score(item), 4), "reasons": _reasons(item)}


def _apply_taste(conn: Connection, lang: str, items: list[dict[str, Any]]) -> dict[int, dict[int, float]]:
    """Score every item; returns the topic vectors, which the variety step uses too."""
    prof = taste.profile(conn, lang)
    measured = [i["id"] for i in items if not i["estimated"] and i["type"] not in MANGA_TYPES]
    vecs = taste.item_vectors(conn, measured, prof.idf) if prof.idf else {}
    ctx = ranker.context(conn, lang, items)
    for item in items:
        factor, reasons = prof.multiplier(item, vecs.get(item["id"]))
        item["_score"] = _base(item) * factor * ranker.boost(item, ctx)
        item["_taste"] = round(factor, 3)
        item["_taste_reasons"] = reasons
    return vecs


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


# Found content near your level. When there's too little of it (a new learner, a new language), the lists are filled
# with the closest found content outside it, so there is always something to watch and read.
IN_BAND = frozenset({"stretch", "i_plus_1", "comfortable"})
MIN_IN_BAND = 30


def in_band(item: dict[str, Any]) -> bool:
    return item["band"] in IN_BAND or item["origin"] != "scraper"


def _never_empty(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    near = [i for i in items if in_band(i)]
    if len(near) >= MIN_IN_BAND:
        return near
    off = [i for i in items if not in_band(i)]
    for item in off:
        item["_fill"] = True
    return near + off[: max(0, 2 * MIN_IN_BAND - len(near))]


def ranked(conn: Connection, lang: str, shelf: str | None) -> list[dict[str, Any]]:
    """Every suggestion for a shelf (None = all), best first, creators spread out."""
    key = (lang, shelf or "all")
    version = _version(conn, lang)
    cached = _RANKED.get(key)
    if cached and cached[1] == version and time.monotonic() - cached[0] < RANK_CACHE_SECONDS:
        return cached[2]
    items = candidates(conn, lang, shelf)
    vectors = _apply_taste(conn, lang, items)
    items.sort(key=lambda i: (-_score(i), i["id"]))
    near = _never_empty(items)
    varied = ranker.diversify(near, _score, vectors)
    result = varied[: ranker.MMR_TOP] + spread_creators(varied[ranker.MMR_TOP :])
    _RANKED[key] = (time.monotonic(), version, result)
    return result


def invalidate() -> None:
    _RANKED.clear()


def _minutes_left(conn: Connection, lang: str) -> float | None:
    """Minutes still to go in today's goal (None once it's met)."""
    from app.db import settings_store
    from app.timeutil import local_day, local_today

    goal = (settings_store.get(conn, "goals", {}) or {}).get(lang, 60)
    rows = conn.execute(
        text(
            "SELECT started_at, active_seconds FROM activity_sessions WHERE language_code = :l AND is_baseline = 0 "
            "AND started_at >= strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-2 days')"
        ),
        {"l": lang},
    ).all()
    today = local_today()
    done = sum(seconds or 0 for started, seconds in rows if local_day(started) == today) / 60
    left = float(goal) - done
    return left if left > 0 else None


def up_next(conn: Connection, lang: str, n: int = 12) -> dict[str, Any]:
    minutes_left = _minutes_left(conn, lang)
    for item in ranked(conn, lang, None):
        fit = ranker.time_fit(item, minutes_left)
        item["_today"] = _score(item) * fit
        item["_time_fit"] = fit > 1 and minutes_left is not None and minutes_left <= 30  # worth saying when time is short

    def today_score(item: dict[str, Any]) -> float:
        return item.get("_today", _score(item))

    pool = sorted(ranked(conn, lang, None), key=today_score, reverse=True)
    # Prefer measured items for the short list; estimated ones fill in only if needed.
    pool.sort(key=lambda i: (i["estimated"], -today_score(i)))
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
    picks.sort(key=today_score, reverse=True)
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
