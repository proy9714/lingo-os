"""How suggestions are ranked: Comprehensible Input Value (docs/RECOMMENDATION.md explains it with examples).

For each item the question is: if you spend your next minutes on it, how much will you learn, how likely are you to
enjoy it, and is it at a level you can follow? A suggestion's score is

    level fit (asymmetric: a bit easy is fine, too hard is not; content_scores.i1_score, calibration.py)
  × confidence (measured items fully; items estimated from their channel or show a little less)
  × taste (channels, sites and shows you engage with, lengths you finish, topics you enjoy: taste.py)
  × exp(Σ weight · part), with the parts:

  learn      learnable new words per minute of your time: words just beyond your vocabulary frontier (not the ones
             you already know, not ones so rare you'll never see them again), counting more when they repeat in the
             item, divided by its minutes (your own reading pace for texts), compared with the other suggestions
  reinforce  words you're learning (or have as familiar) that it brings back, each worth more the more it has faded
             from memory (engine/memory.py): words come back through content, never through flashcards
  speed      a video spoken much faster than the ones you finish is harder than its words alone say
  series     the next episode or volume of something you're following
  recent     news and podcast episodes from the last few weeks
  skipped    a card you scrolled past several times without opening sinks; the evidence fades after a few weeks

The weights start from hand-set values and are then learned from what you do (fit_weights): which cards you opened
among those you were shown, a regularised logistic regression pulled toward the hand-set values until there's enough
evidence, refitted at most daily.

Then the list is built place by place (diversify): each place goes to the suggestion with the best score after a
penalty for looking like the ones just placed (same channel, similar topic, same length, same kind) and for bringing
back words the list already brings back. Every seventh place (starting with the third) goes to the most promising item
the model knows least about (estimated, or a channel or show you haven't tried): exploring, so the model keeps
learning what you like. Today's short list also prefers what fits the minutes left in your daily goal.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from datetime import timedelta
from typing import Any

from sqlalchemy import Connection, text

from app.timeutil import from_iso, to_iso, utc_now

WEIGHTS = {"learn": 0.55, "reinforce": 0.5, "speed": 1.0, "series": 0.45, "recent": 0.3, "skipped": 1.0}
LEARNED = ("learn", "reinforce", "speed", "series", "recent")  # weights fitted to you (skipped is itself an outcome)
WEIGHT_RANGE = (0.25, 2.5)  # a fitted weight stays within this multiple of its hand-set value
COMMON_RANK = 5000  # kept for teach_shares (older callers)
UNKNOWN_RANK = 1500
REINFORCE_CAP = 6.0  # more than this many faded words adds nothing
SKIP_FREE = 2  # a card may be passed this many times before it starts to sink
SKIP_STEP, SKIP_FLOOR = 0.2, -1.0
SKIP_HALF_LIFE_DAYS = 21.0  # passing a card by counts half as much three weeks later
SEEN_EVERY = timedelta(hours=6)  # a card on screen counts once per 6 hours, not once per scroll
RECENT_DAYS = 21.0
READING_WPM = 150.0  # until your own pace is known
MMR_LAMBDA, MMR_WINDOW, MMR_TOP, MMR_LOOKAHEAD = 0.7, 4, 160, 40
WORD_OVERLAP_PENALTY = 0.35
EXPLORE_FIRST, EXPLORE_EVERY, EXPLORE_BONUS = 2, 7, 0.8
FIT_EVERY = timedelta(days=1)
MIN_IMPRESSIONS = 30


# ------------------------------------------------------------------ signals (kept)


def due_words(conn: Connection, lang: str) -> dict[int, float]:
    """Words you're learning, each with how due it is to come back (0 = met recently … 1 = due)."""
    rows = conn.execute(
        text(
            "SELECT w.lexeme_id, COALESCE(w.status_changed_at, w.first_seen_at), w.last_lookup_at, m.last_met, COALESCE(m.days, 0) "
            "FROM user_words w JOIN lexemes l ON l.id = w.lexeme_id "
            "LEFT JOIN (SELECT cl.lexeme_id, MAX(s.started_at) AS last_met, COUNT(DISTINCT substr(s.started_at, 1, 10)) AS days "
            " FROM content_lemmas cl JOIN activity_sessions s ON s.content_item_id = cl.content_item_id "
            " JOIN user_words u ON u.lexeme_id = cl.lexeme_id AND u.status = 'learning' "
            " WHERE s.is_baseline = 0 GROUP BY cl.lexeme_id) m ON m.lexeme_id = w.lexeme_id "
            "WHERE w.status = 'learning' AND l.language_code = :l"
        ),
        {"l": lang},
    ).all()
    now = utc_now()
    out = {}
    for lexeme_id, since, looked_up, met, days in rows:
        last = max((t for t in (met, looked_up, since) if t), default=None)
        if not last:
            out[lexeme_id] = 1.0
            continue
        interval = 2.0 ** min(int(days), 5)  # 1, 2, 4, 8, 16, 32 days
        elapsed = max(0.0, (now - from_iso(last)).total_seconds() / 86400)
        out[lexeme_id] = min(1.0, elapsed / interval)
    return out


def learning_in(conn: Connection, item_ids: list[int], lexemes: set[int]) -> dict[int, list[int]]:
    if not item_ids or not lexemes:
        return {}
    rows = conn.execute(
        text(
            f"SELECT content_item_id, lexeme_id FROM content_lemmas WHERE content_item_id IN ({','.join(map(str, item_ids))}) "
            f"AND lexeme_id IN ({','.join(map(str, lexemes))})"
        )
    ).all()
    out: dict[int, list[int]] = defaultdict(list)
    for item_id, lexeme_id in rows:
        out[item_id].append(lexeme_id)
    return out


def teach_shares(conn: Connection, item_ids: list[int]) -> dict[int, tuple[float, int]]:
    """Per measured item: the share of its probably-unknown words that are common ones, and how many unknown words."""
    if not item_ids:
        return {}
    rows = conn.execute(
        text(
            "SELECT cl.content_item_id, SUM(CASE WHEN COALESCE(l.freq_rank, 999999) <= :common THEN 1 ELSE 0 END), COUNT(*) "
            "FROM content_lemmas cl JOIN lexemes l ON l.id = cl.lexeme_id LEFT JOIN user_words w ON w.lexeme_id = cl.lexeme_id "
            f"WHERE cl.content_item_id IN ({','.join(map(str, item_ids))}) AND l.is_proper = 0 "
            "AND (w.status IN ('seen', 'learning') OR (w.status IS NULL AND COALESCE(l.freq_rank, 999999) > :unknown)) "
            "GROUP BY cl.content_item_id"
        ),
        {"common": COMMON_RANK, "unknown": UNKNOWN_RANK},
    ).all()
    return {item_id: ((useful or 0) / total if total else 0.0, int(total)) for item_id, useful, total in rows}


def comfort_wpm(conn: Connection, lang: str) -> float | None:
    """How fast the videos you finish usually are (words a minute); None until three of them say so."""
    rows = conn.execute(
        text(
            "SELECT ca.speech_wpm FROM content_items ci JOIN content_analysis ca ON ca.content_item_id = ci.id "
            "LEFT JOIN (SELECT content_item_id, SUM(active_seconds) AS secs FROM activity_sessions WHERE is_baseline = 0 "
            " GROUP BY content_item_id) s ON s.content_item_id = ci.id "
            "WHERE ci.language_code = :l AND ca.speech_wpm > 0 AND ci.duration_sec > 0 "
            "AND (ci.status = 'finished' OR COALESCE(s.secs, 0) >= 0.6 * ci.duration_sec)"
        ),
        {"l": lang},
    ).all()
    speeds = sorted(r[0] for r in rows)
    if len(speeds) < 3:
        return None
    return speeds[int(len(speeds) * 0.75)]  # comfortable up to what most of your finished videos reach


def record_seen(conn: Connection, item_ids: list[int]) -> int:
    """Cards that were on screen. Each counts at most once every 6 hours."""
    now = utc_now()
    counted = 0
    for item_id in dict.fromkeys(item_ids):
        result = conn.execute(
            text(
                "INSERT INTO item_impressions (content_item_id, shown, first_shown_at, last_shown_at) "
                "SELECT :i, 1, :now, :now WHERE EXISTS (SELECT 1 FROM content_items WHERE id = :i) "
                "ON CONFLICT(content_item_id) DO UPDATE SET shown = shown + 1, last_shown_at = :now "
                "WHERE item_impressions.last_shown_at IS NULL OR item_impressions.last_shown_at < :before"
            ),
            {"i": item_id, "now": to_iso(now), "before": to_iso(now - SEEN_EVERY)},
        )
        counted += result.rowcount or 0
    return counted


def skipped_owners(conn: Connection, lang: str) -> dict[str, float]:
    """Channels and sites whose cards you keep passing by: weight of evidence against them."""
    from app.services.catalog import name_key
    from app.services.taste import owner_of

    rows = conn.execute(
        text(
            "SELECT ci.type, ci.creator, json_extract(ci.metadata_json, '$.site'), ii.shown FROM item_impressions ii "
            "JOIN content_items ci ON ci.id = ii.content_item_id WHERE ci.language_code = :l AND ii.shown > :free "
            "AND ci.last_opened_at IS NULL AND NOT EXISTS (SELECT 1 FROM activity_sessions s WHERE s.content_item_id = ci.id)"
        ),
        {"l": lang, "free": SKIP_FREE},
    ).all()
    out: dict[str, float] = defaultdict(float)
    for item_type, creator, site, shown in rows:
        owner = owner_of(item_type, creator, site)
        if owner:
            out[name_key(owner)] += 0.15 * min(shown - SKIP_FREE, 4)
    return dict(out)


# ------------------------------------------------------------------ new signals


def learn_values(conn: Connection, item_ids: list[int], r50: float) -> dict[int, float]:
    """Per measured item: how many new words it can teach you, roughly.

    Each word you don't know yet counts by three things: how likely you are not to know it (from its frequency rank
    relative to your frontier r50, or what you've told the app), whether it repeats in the item (once: you may not
    even notice it; three times: you'll likely pick it up) and whether it's worth learning now (within about 8× your
    frontier; rarer words count a little). Words you're learning are left out here: they count under `reinforce`."""
    if not item_ids:
        return {}
    rows = conn.execute(
        text(
            "SELECT cl.content_item_id, SUM("
            " (1.0 - CASE WHEN w.status IN ('known', 'ignored', 'learning', 'familiar') THEN 1.0 "
            "   WHEN w.status = 'seen' THEN MIN(w.p_known, 0.5) "
            "   WHEN l.freq_rank IS NULL THEN 0.05 WHEN l.freq_rank <= :r1 THEN 0.85 WHEN l.freq_rank <= :r2 THEN 0.45 "
            "   WHEN l.freq_rank <= :r4 THEN 0.18 ELSE 0.05 END) "
            " * CASE WHEN cl.count >= 3 THEN 1.0 WHEN cl.count = 2 THEN 0.7 ELSE 0.35 END "
            " * CASE WHEN l.freq_rank IS NULL THEN 0.1 WHEN l.freq_rank <= :r8 THEN 1.0 WHEN l.freq_rank <= 20000 THEN 0.4 ELSE 0.1 END"
            ") FROM content_lemmas cl JOIN lexemes l ON l.id = cl.lexeme_id LEFT JOIN user_words w ON w.lexeme_id = cl.lexeme_id "
            f"WHERE cl.content_item_id IN ({','.join(map(str, item_ids))}) AND l.is_proper = 0 GROUP BY cl.content_item_id"
        ),
        {"r1": r50, "r2": 2 * r50, "r4": 4 * r50, "r8": 8 * r50},
    ).all()
    return {item_id: float(value or 0.0) for item_id, value in rows}


def reading_wpm(conn: Connection, lang: str) -> float:
    """How fast you read (words a minute), from texts you read most of; 150 until there are three of them."""
    rows = conn.execute(
        text(
            "SELECT ci.word_count * MIN(1.0, MAX(ci.progress, CASE WHEN ci.status = 'finished' THEN 1.0 ELSE 0 END)) / (SUM(s.active_seconds) / 60.0) "
            "FROM content_items ci JOIN activity_sessions s ON s.content_item_id = ci.id "
            "WHERE ci.language_code = :l AND ci.type IN ('article', 'text', 'epub', 'pdf') AND ci.word_count > 0 AND s.is_baseline = 0 "
            "AND (ci.status = 'finished' OR ci.progress >= 0.6) GROUP BY ci.id HAVING SUM(s.active_seconds) >= 120"
        ),
        {"l": lang},
    ).all()
    speeds = sorted(r[0] for r in rows if r[0])
    if len(speeds) < 3:
        return READING_WPM
    return max(40.0, min(400.0, statistics.median(speeds)))


def minutes_of(item: dict[str, Any], wpm: float) -> float | None:
    if item.get("duration_sec"):
        return item["duration_sec"] / 60
    if item.get("word_count"):
        return item["word_count"] / wpm
    return None


def series_next(conn: Connection, lang: str, item_ids: list[int]) -> set[int]:
    """Items that are the next episode or volume after the last one you watched or read in a series."""
    if not item_ids:
        return set()
    rows = conn.execute(
        text(
            "SELECT ci.id FROM content_items ci JOIN ("
            " SELECT c.collection_id, MAX(c.collection_index) AS last FROM content_items c "
            " WHERE c.language_code = :l AND c.collection_id IS NOT NULL AND c.collection_index IS NOT NULL "
            " AND (c.status = 'finished' OR c.progress >= 0.5 OR EXISTS (SELECT 1 FROM activity_sessions s WHERE s.content_item_id = c.id "
            "  AND s.is_baseline = 0 AND s.active_seconds >= 120)) GROUP BY c.collection_id) done ON done.collection_id = ci.collection_id "
            f"WHERE ci.id IN ({','.join(map(str, item_ids))}) AND ci.collection_index > done.last "
            "AND ci.collection_index <= done.last + 1"
        ),
        {"l": lang},
    ).all()
    return {r[0] for r in rows}


def published_ages(conn: Connection, item_ids: list[int]) -> dict[int, float]:
    """Days since publication, for news and podcast episodes that say when they were published."""
    if not item_ids:
        return {}
    rows = conn.execute(
        text(
            f"SELECT id, published_at FROM content_items WHERE id IN ({','.join(map(str, item_ids))}) "
            "AND type IN ('article', 'podcast_episode') AND published_at IS NOT NULL"
        )
    ).all()
    now = utc_now()
    out = {}
    for item_id, published in rows:
        try:
            out[item_id] = max(0.0, (now - from_iso(published)).total_seconds() / 86400)
        except ValueError:
            continue
    return out


def tried_owners(conn: Connection, lang: str) -> set[str]:
    """Channels, sites and shows you've spent time on (the others are new to you: worth exploring)."""
    from app.services.catalog import name_key
    from app.services.taste import owner_of

    rows = conn.execute(
        text(
            "SELECT DISTINCT ci.type, ci.creator, json_extract(ci.metadata_json, '$.site') FROM content_items ci "
            "JOIN activity_sessions s ON s.content_item_id = ci.id WHERE ci.language_code = :l AND s.is_baseline = 0"
        ),
        {"l": lang},
    ).all()
    return {name_key(owner) for t, c, site in rows if (owner := owner_of(t, c, site))}


def recall_of_learning(conn: Connection, lang: str) -> dict[int, float]:
    """How well you'd recognise each word you're learning right now (the memory model), 0..1."""
    try:
        from app.engine import memory

        return memory.recall_now(conn, lang)
    except Exception:  # noqa: BLE001 - the ranking must never fail over the memory model: fall back to the schedule
        return {lexeme: 1.0 - due for lexeme, due in due_words(conn, lang).items()}


# ------------------------------------------------------------------ scoring


def parts(item: dict[str, Any], ctx: dict[str, Any]) -> dict[str, float]:
    """Each part's contribution (0 = neutral) for one suggestion."""
    out = {"learn": 0.0, "reinforce": 0.0, "speed": 0.0, "series": 0.0, "recent": 0.0, "skipped": 0.0}
    learn = ctx.get("learn", {}).get(item["id"])
    median = ctx.get("learn_median")
    if not item["estimated"] and learn is not None and median:
        out["learn"] = 0.5 * max(-1.0, min(1.0, math.log2(max(learn, 1e-3) / median)))
    recall = ctx.get("recall", {})
    faded = [1.0 - recall.get(lex, 0.0) for lex in ctx.get("learning", {}).get(item["id"], [])]
    need = sum(faded)
    if need:
        out["reinforce"] = math.log1p(min(need, REINFORCE_CAP)) / math.log1p(REINFORCE_CAP)
    comfort, wpm = ctx.get("comfort"), item.get("speech_wpm")
    if comfort and wpm:
        out["speed"] = -min(0.5, max(0.0, (wpm - comfort * 1.15) / comfort))
    if item["id"] in ctx.get("series", ()):
        out["series"] = 1.0
    age = ctx.get("ages", {}).get(item["id"])
    if age is not None:
        out["recent"] = math.exp(-age / RECENT_DAYS)
    shown = ctx.get("shown", {}).get(item["id"], 0)
    if shown > SKIP_FREE and item["status"] != "in_progress":
        out["skipped"] = max(SKIP_FLOOR, -SKIP_STEP * (shown - SKIP_FREE))
    item["_due_words"] = sum(1 for f in faded if f >= 0.5)  # words that have faded enough to say so
    item["_learn"] = learn
    item["_series"] = out["series"] > 0
    return out


def impressions(conn: Connection, item_ids: list[int]) -> dict[int, float]:
    """Times each card was on screen, fading with time (half the weight three weeks later)."""
    if not item_ids:
        return {}
    rows = conn.execute(
        text(f"SELECT content_item_id, shown, last_shown_at FROM item_impressions WHERE content_item_id IN ({','.join(map(str, item_ids))})")
    ).all()
    now = utc_now()
    out = {}
    for item_id, shown, last in rows:
        age = max(0.0, (now - from_iso(last)).total_seconds() / 86400) if last else 0.0
        out[item_id] = shown * 0.5 ** (age / SKIP_HALF_LIFE_DAYS)
    return out


def context(conn: Connection, lang: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    from app.engine.profile import get_profile

    ids = [i["id"] for i in items]
    measured = [i["id"] for i in items if not i["estimated"]]
    profile = get_profile(conn, lang)
    r50 = float(profile["r50"]) if profile else 800.0
    wpm = reading_wpm(conn, lang)
    raw = learn_values(conn, measured, r50)
    by_id = {i["id"]: i for i in items}
    learn = {}
    for item_id, value in raw.items():
        minutes = minutes_of(by_id[item_id], wpm)
        learn[item_id] = value / max(minutes, 1.0) if minutes else value / 10.0
    recall = recall_of_learning(conn, lang)
    ctx = {
        "learn": learn,
        "learn_median": statistics.median(learn.values()) if len(learn) >= 2 else None,
        "recall": recall,
        "learning": learning_in(conn, measured, set(recall)),
        "comfort": comfort_wpm(conn, lang),
        "shown": impressions(conn, ids),
        "series": series_next(conn, lang, ids),
        "ages": published_ages(conn, ids),
        "tried": tried_owners(conn, lang),
        "wpm": wpm,
    }
    ctx["weights"] = fitted_weights(conn, lang)
    return ctx


def boost(item: dict[str, Any], ctx: dict[str, Any]) -> float:
    contributions = parts(item, ctx)
    weights = ctx.get("weights") or WEIGHTS
    item["_parts"] = {k: round(v, 3) for k, v in contributions.items() if v}
    item["_weights"] = {k: round(weights.get(k, WEIGHTS[k]), 3) for k in item["_parts"]}
    return math.exp(sum(weights.get(k, WEIGHTS[k]) * v for k, v in contributions.items()))


# ------------------------------------------------------------------ learning the weights from what you open


def fitted_weights(conn: Connection, lang: str) -> dict[str, float]:
    from app.db import settings_store

    stored = settings_store.get(conn, f"reco_weights.{lang}") or {}
    return {k: float(stored.get("weights", {}).get(k, v)) for k, v in WEIGHTS.items()}


def fit_weights(conn: Connection, lang: str, rows: list[tuple[dict[str, float], bool]], *, force: bool = False) -> dict[str, Any]:
    """Fit the part weights to which shown cards you opened: logistic regression with a Gaussian prior centred on
    the hand-set weights (so a few clicks nudge them, a few hundred can move them), by Newton's method.

    `rows` holds, for each card you were shown, its parts and whether you opened it."""
    import numpy as np

    from app.db import settings_store

    key = f"reco_weights.{lang}"
    stored = settings_store.get(conn, key) or {}
    if not force and stored.get("fitted_at") and utc_now() - from_iso(stored["fitted_at"]) < FIT_EVERY:
        return stored
    if len(rows) < MIN_IMPRESSIONS or len({opened for _, opened in rows}) < 2:
        out = {"fitted_at": to_iso(utc_now()), "weights": dict(WEIGHTS), "impressions": len(rows), "fitted": False}
        settings_store.put(conn, key, out)
        return out
    names = list(LEARNED)
    x = np.array([[1.0] + [p.get(n, 0.0) for n in names] for p, _ in rows])
    y = np.array([1.0 if opened else 0.0 for _, opened in rows])
    prior = np.array([0.0] + [WEIGHTS[n] for n in names])
    precision = np.array([1e-4] + [4.0] * len(names))  # how firmly the weights hold to the hand-set values
    beta = prior.copy()
    base_rate = min(0.95, max(0.05, y.mean()))
    beta[0] = math.log(base_rate / (1 - base_rate))
    for _ in range(25):
        p = 1.0 / (1.0 + np.exp(-(x @ beta)))
        gradient = x.T @ (y - p) - precision * (beta - prior)
        hessian = -(x.T * (p * (1 - p))) @ x - np.diag(precision)
        step = np.linalg.solve(hessian, gradient)
        beta -= step
        if np.max(np.abs(step)) < 1e-6:
            break
    weights = dict(WEIGHTS)
    for n, value in zip(names, beta[1:]):
        low, high = WEIGHTS[n] * WEIGHT_RANGE[0], WEIGHTS[n] * WEIGHT_RANGE[1]
        weights[n] = round(float(min(high, max(low, value))), 4)
    out = {
        "fitted_at": to_iso(utc_now()),
        "weights": weights,
        "impressions": len(rows),
        "opened": int(y.sum()),
        "fitted": True,
    }
    settings_store.put(conn, key, out)
    return out


# ------------------------------------------------------------------ building the list: variety and exploring


def _cosine(a: dict[int, float] | None, b: dict[int, float] | None) -> float:
    if not a or not b:
        return 0.0
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(k, 0.0) for k, v in a.items())


def similarity(a: dict[str, Any], b: dict[str, Any], vectors: dict[int, dict[int, float]]) -> float:
    from app.services.catalog import name_key
    from app.services.taste import length_bucket, owner_of

    sim = 0.0
    owner_a = owner_of(a["type"], a.get("creator"), a.get("site"))
    if owner_a and name_key(owner_a) == name_key(owner_of(b["type"], b.get("creator"), b.get("site")) or ""):
        sim += 1.0
    sim += 0.6 * max(0.0, _cosine(vectors.get(a["id"]), vectors.get(b["id"])))
    bucket = length_bucket(a["type"], a.get("duration_sec"), a.get("word_count"))
    if bucket and bucket == length_bucket(b["type"], b.get("duration_sec"), b.get("word_count")):
        sim += 0.25
    if a.get("kind") and a.get("kind") == b.get("kind"):
        sim += 0.15
    return sim


def is_uncertain(item: dict[str, Any], tried: set[str]) -> bool:
    """An item the model knows little about: its level is only estimated, or it's from a channel or show you haven't
    spent time on yet."""
    from app.services.catalog import name_key
    from app.services.taste import owner_of

    if item.get("estimated"):
        return True
    owner = owner_of(item["type"], item.get("creator"), item.get("site"))
    return bool(owner) and name_key(owner) not in tried


def diversify(
    items: list[dict[str, Any]],
    score_of,  # noqa: ANN001
    vectors: dict[int, dict[int, float]],
    ctx: dict[str, Any] | None = None,
    *,
    explore: bool = True,
) -> list[dict[str, Any]]:
    """Build the best part of the list place by place (the rest keeps its order).

    Each place goes to the item with the best log-score after penalties for resembling the last few placed items and
    for words the list already brings back (the value of meeting a word you're learning shrinks with each item that
    already brings it back). Exploring places (the 3rd, 10th, 17th…) go to the best item the model is unsure about,
    with a bonus: the way it keeps learning what you like and keeps estimated finds from never being tried."""
    head, tail = items[:MMR_TOP], items[MMR_TOP:]
    learning = (ctx or {}).get("learning", {})
    tried = (ctx or {}).get("tried", set())
    covered: set[int] = set()
    out: list[dict[str, Any]] = []
    while head:
        position = len(out)
        exploring = explore and ctx is not None and position >= EXPLORE_FIRST and (position - EXPLORE_FIRST) % EXPLORE_EVERY == 0
        recent = out[-MMR_WINDOW:]
        best_index, best_value = -1, -math.inf
        for index, item in enumerate(head[:MMR_LOOKAHEAD]):
            if exploring and not is_uncertain(item, tried):
                continue
            penalty = max((similarity(item, other, vectors) for other in recent), default=0.0)
            words = learning.get(item["id"], [])
            overlap = (sum(1 for w in words if w in covered) / len(words)) if words else 0.0
            value = math.log(max(score_of(item), 1e-6)) - MMR_LAMBDA * penalty - WORD_OVERLAP_PENALTY * overlap
            if exploring:
                value += EXPLORE_BONUS
            if value > best_value:
                best_index, best_value = index, value
        if best_index < 0:  # nothing uncertain left near the top: an ordinary place
            best_index = max(
                range(min(len(head), MMR_LOOKAHEAD)),
                key=lambda i: math.log(max(score_of(head[i]), 1e-6))
                - MMR_LAMBDA * max((similarity(head[i], o, vectors) for o in recent), default=0.0),
            )
            exploring = False
        chosen = head.pop(best_index)
        chosen["_explore"] = exploring
        covered.update(learning.get(chosen["id"], []))
        out.append(chosen)
    return out + tail


# ------------------------------------------------------------------ today: the time you have left


def time_fit(item: dict[str, Any], minutes_left: float | None, wpm: float = READING_WPM) -> float:
    """×1.15 for what fits in the minutes left today, ×0.8 for what's more than twice as long."""
    if not minutes_left or minutes_left < 5:
        return 1.0
    minutes = minutes_of(item, wpm)
    if minutes is None:
        return 1.0
    if minutes <= minutes_left * 1.25:
        return 1.15
    return 0.8 if minutes > minutes_left * 2 else 1.0
