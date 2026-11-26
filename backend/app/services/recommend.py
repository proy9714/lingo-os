"""What to watch and read next: matched to your level and your taste, never something you've already watched.

score = level fit × freshness × confidence × taste × what it's worth to you now (Comprehensible Input Value)
  level fit      how close the item is to your "just right" coverage, calibrated by your difficulty ratings; a bit too
                 easy costs less than a bit too hard (services/calibration.py)
  freshness      unfinished books and manga you started get a boost
  confidence     measured items count fully; items whose level is estimated from their channel count a little less
  taste          what you tend to finish, come back to or dismiss: channels (sampled, so new ones get tried), sites,
                 topics, length (services/taste.py)
  worth          learnable new words per minute, words you're learning that have started to fade, speech speed, the
                 next episode of a series, how recent news and podcasts are, cards you keep passing by; the weights
                 are learned from what you open (services/ranker.py)
The list is then built place by place for variety (channel, topic, length, kind, words brought back), with some places
for exploring; Today keeps that order and prefers what fits the minutes left in your daily goal. docs/RECOMMENDATION.md
explains it all with examples.
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


def candidates(conn: Connection, lang: str, shelf: str | None = None, *, shown_only: bool = False) -> list[dict[str, Any]]:
    """Everything that may be suggested, with its score inputs. `shelf` limits it to 'watch', 'listen', 'read' or
    'manga'. `shown_only` instead lists every card you've been shown, whatever became of it (to learn from)."""
    types = SHELVES.get(shelf) if shelf else WATCH_TYPES + READ_TYPES + MANGA_TYPES
    type_list = ", ".join(f"'{t}'" for t in types or ())
    rows = conn.execute(
        text(
            "SELECT ci.id, ci.type, ci.title, ci.creator, ci.source, ci.external_id, ci.source_url, ci.duration_sec, "
            "ci.word_count, ci.status, ci.progress, ci.origin, ci.metadata_json, cs.coverage, cs.i1_score, cs.band, "
            "cs.expected_unknown, cs.estimated, "
            "CASE WHEN cs.estimated = 1 THEN 0 ELSE (SELECT COUNT(*) FROM content_lemmas cl JOIN user_words w "
            " ON w.lexeme_id = cl.lexeme_id WHERE cl.content_item_id = ci.id AND w.status IN ('learning', 'familiar')) END AS learning_words, "
            "(SELECT COUNT(*) FROM activity_sessions s WHERE s.content_item_id = ci.id AND s.is_baseline = 0) AS watched, "
            "ca.speech_wpm"
            + (", (ci.last_opened_at IS NOT NULL OR EXISTS (SELECT 1 FROM activity_sessions s2 WHERE s2.content_item_id = ci.id)) " if shown_only else " ")
            + "FROM content_items ci JOIN content_scores cs ON cs.content_item_id = ci.id "
            "LEFT JOIN content_analysis ca ON ca.content_item_id = ci.id "
            f"WHERE ci.language_code = :l AND ci.type IN ({type_list}) "
            + (
                "AND EXISTS (SELECT 1 FROM item_impressions ii WHERE ii.content_item_id = ci.id) "
                if shown_only
                else "AND ci.status NOT IN ('dismissed', 'archived', 'finished') "
                "AND (ci.analysis_status = 'done' OR cs.estimated = 1) "
                f"AND NOT (ci.type IN ({WATCHED_TYPES}) AND {content.WATCHED_SQL})"
            )
        ),
        {"l": lang},
    ).all()
    out = []
    for row in rows:
        item = dict(zip(_KEYS + ("opened",), row)) if shown_only else dict(zip(_KEYS, row))
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
    if item.get("_series"):
        reasons.append("the next one in a series you're following")
    reasons += item.get("_taste_reasons", [])
    faded = item.get("_due_words", 0)
    if faded:
        reasons.append(f"brings back {faded} {'word' if faded == 1 else 'words'} you're learning, just as they start to fade")
    elif item["learning_words"]:
        reasons.append(f"brings back {item['learning_words']} of your saved words")
    if (item.get("_parts") or {}).get("learn", 0) >= 0.2:
        reasons.append("teaches more new words you're ready for than most")
    if (item.get("_parts") or {}).get("recent", 0) >= 0.5:
        reasons.append("new this week")
    if item.get("_explore"):
        reasons.append("something new to try: it helps the suggestions learn what you like")
    if item.get("_time_fit"):
        reasons.append("fits the time left in today's goal")
    if item.get("_fill"):
        reasons.append("the closest to your level found so far")
    if item["estimated"]:
        if item["type"] in PODCAST_TYPES:
            reasons.append("level estimated from the show's other episodes" if item["level_basis"] in ("channel1", "channel3")
                           else "level not measured yet (no transcript)")
        else:
            reasons.append({"label": "level estimated from the channel's label", "language": "a learner channel, level not measured yet"}
                           .get(item["level_basis"] or "", "level estimated from the channel"))
    return reasons


def explain(item: dict[str, Any]) -> dict[str, Any]:
    """The score taken apart: level fit × freshness × confidence × taste × exp(Σ weight · part)."""
    freshness = 1.25 if item["status"] == "in_progress" and (item["progress"] or 0) < 0.9 else 1.0
    confidence = CONFIDENCE.get(item["level_basis"] or "", 0.8) if item["estimated"] else 1.0
    return {
        "fit": round(item["i1_score"] or 0.0, 3),
        "freshness": freshness,
        "confidence": confidence,
        "taste": item.get("_taste", 1.0),
        "parts": item.get("_parts", {}),
        "weights": item.get("_weights", {}),
        "explore": bool(item.get("_explore")),
    }


def _present(item: dict[str, Any]) -> dict[str, Any]:
    clean = {k: v for k, v in item.items() if not k.startswith("_")}
    return {**clean, "kind": kind_of(item), "score": round(_score(item), 4), "reasons": _reasons(item), "explain": explain(item)}


def _apply_taste(conn: Connection, lang: str, items: list[dict[str, Any]]) -> tuple[dict[int, dict[int, float]], dict[str, Any]]:
    """Score every item; returns the topic vectors and the ranking context, which the list building uses too."""
    prof = taste.profile(conn, lang)
    measured = [i["id"] for i in items if not i["estimated"] and i["type"] not in MANGA_TYPES]
    vecs = taste.item_vectors(conn, measured, prof.idf) if prof.idf else {}
    ctx = ranker.context(conn, lang, items)
    for item in items:
        factor, reasons = prof.multiplier(item, vecs.get(item["id"]))
        item["_score"] = _base(item) * factor * ranker.boost(item, ctx)
        item["_taste"] = round(factor, 3)
        item["_taste_reasons"] = reasons
    return vecs, ctx


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
    """What the ranking depends on: when any of it changes, the cached order is rebuilt (cards being shown are left out
    on purpose, so scrolling through a list never reshuffles it)."""
    return tuple(
        conn.execute(
            text(
                "SELECT (SELECT MAX(id) FROM content_items), (SELECT COUNT(*) FROM content_items WHERE language_code = :l "
                "AND status IN ('dismissed', 'finished')), (SELECT MAX(computed_at) FROM content_scores), "
                "(SELECT MAX(id) FROM activity_sessions), "
                "(SELECT group_concat(key || '=' || value_json) FROM app_settings WHERE key IN (:k1, :k2, :k3, :k4)), "
                "(SELECT MAX(status_changed_at) FROM user_words), (SELECT COUNT(*) FROM user_words)"
            ),
            {
                "l": lang, "k1": f"calibration.{lang}.listening", "k2": f"calibration.{lang}.reading",
                "k3": f"band_shift.{lang}", "k4": f"reco_weights.{lang}",
            },
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
    learn_weights(conn, lang)
    items = candidates(conn, lang, shelf)
    vectors, ctx = _apply_taste(conn, lang, items)
    items.sort(key=lambda i: (-_score(i), i["id"]))
    near = _never_empty(items)
    varied = ranker.diversify(near, _score, vectors, ctx)
    result = varied[: ranker.MMR_TOP] + spread_creators(varied[ranker.MMR_TOP :])
    _RANKED[key] = (time.monotonic(), version, result)
    _CONTEXT[key] = (vectors, ctx)
    return result


_CONTEXT: dict[tuple[str, str], tuple[dict[int, dict[int, float]], dict[str, Any]]] = {}


def learn_weights(conn: Connection, lang: str, *, force: bool = False) -> dict[str, Any]:
    """Refit the part weights to which cards you opened (at most once a day; ranker.fit_weights)."""
    from app.db import settings_store
    from app.timeutil import from_iso, utc_now

    stored = settings_store.get(conn, f"reco_weights.{lang}") or {}
    if not force and stored.get("fitted_at") and utc_now() - from_iso(stored["fitted_at"]) < ranker.FIT_EVERY:
        return stored
    shown = candidates(conn, lang, None, shown_only=True)
    if not shown:
        return ranker.fit_weights(conn, lang, [], force=True)
    ctx = ranker.context(conn, lang, shown)
    ctx["shown"] = {}  # being passed by is the outcome here, not a feature
    rows = [(ranker.parts(item, ctx), bool(item.get("opened"))) for item in shown]
    return ranker.fit_weights(conn, lang, rows, force=True)


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
    everything = ranked(conn, lang, None)
    vectors, ctx = _CONTEXT.get((lang, "all"), ({}, {}))
    wpm = ctx.get("wpm", ranker.READING_WPM)
    for item in everything:
        fit = ranker.time_fit(item, minutes_left, wpm)
        item["_today"] = _score(item) * fit
        item["_time_fit"] = fit > 1 and minutes_left is not None and minutes_left <= 30  # worth saying when time is short

    def today_score(item: dict[str, Any]) -> float:
        return item.get("_today", _score(item))

    # The list is built again with today's time in mind, keeping its variety and its exploring places: estimated items
    # come in through those places rather than crowding the short list.
    head = sorted(everything[: ranker.MMR_TOP], key=lambda i: (i["estimated"] and not i.get("_explore"), -today_score(i)))
    pool = ranker.diversify(head, today_score, vectors, ctx)
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
    order = {id(item): index for index, item in enumerate(pool)}
    picks.sort(key=lambda item: order.get(id(item), len(order)))  # the stretch/comfortable picks take their place too
    return {"language": lang, "available": len(everything), "picks": [_present(item) for item in picks[:n]]}


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
