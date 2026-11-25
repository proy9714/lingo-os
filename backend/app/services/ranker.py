"""How suggestions are ranked: what each one teaches you, how well it fits, what you enjoy, and some variety.

A suggestion's score is its level fit (how much of it you'll understand, from `content_scores.i1_score`) times
exp(sum of the parts below), times your taste (services/taste.py: channels sampled from what's known about them,
lengths, topics):

  teach    which new words it would teach: a share of the words you probably don't know that are among the 5,000 most
           common is worth learning; a video full of rare words teaches less for the same effort
  due      words you're learning that it brings back, each weighted by how long ago you last met one in something you
           watched or read (1 day after the first meeting, then 2, 4, 8… days: the spacing of memory, through content,
           never flashcards)
  speed    a video spoken much faster than the videos you finish is harder than its words alone say
  skipped  a card you've scrolled past several times without opening sinks a little more each time

Then the list is re-ranked for variety: each place goes to the best remaining suggestion after a penalty for looking
like the few just placed (same channel, similar topic, same length, same kind). Today's short list also prefers what
fits the minutes left in your daily goal.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import timedelta
from typing import Any

from sqlalchemy import Connection, text

from app.timeutil import from_iso, to_iso, utc_now

WEIGHTS = {"teach": 0.5, "due": 0.45, "speed": 1.0, "skipped": 1.0}
COMMON_RANK = 5000  # "useful" new words: among the most common
UNKNOWN_RANK = 1500  # a word with no status beyond this rank is counted as probably unknown
DUE_CAP = 6.0  # more than this many due words adds nothing
SKIP_FREE = 2  # a card may be passed this many times before it starts to sink
SKIP_STEP, SKIP_FLOOR = 0.2, -1.0
SEEN_EVERY = timedelta(hours=6)  # a card on screen counts once per 6 hours, not once per scroll
MMR_LAMBDA, MMR_WINDOW, MMR_TOP, MMR_LOOKAHEAD = 0.7, 4, 160, 40


# ------------------------------------------------------------------ signals


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


def impressions(conn: Connection, item_ids: list[int]) -> dict[int, int]:
    if not item_ids:
        return {}
    rows = conn.execute(
        text(f"SELECT content_item_id, shown FROM item_impressions WHERE content_item_id IN ({','.join(map(str, item_ids))})")
    ).all()
    return dict(rows)


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


# ------------------------------------------------------------------ scoring


def parts(item: dict[str, Any], ctx: dict[str, Any]) -> dict[str, float]:
    """Each part's contribution (0 = neutral) for one suggestion."""
    out = {"teach": 0.0, "due": 0.0, "speed": 0.0, "skipped": 0.0}
    share, unknown = ctx["teach"].get(item["id"], (0.0, 0))
    if not item["estimated"] and unknown >= 3:
        out["teach"] = share - 0.5
    due = sum(ctx["due"].get(lex, 0.0) for lex in ctx["learning"].get(item["id"], []))
    if due:
        out["due"] = math.log1p(min(due, DUE_CAP)) / math.log1p(DUE_CAP)
    comfort, wpm = ctx.get("comfort"), item.get("speech_wpm")
    if comfort and wpm:
        out["speed"] = -min(0.5, max(0.0, (wpm - comfort * 1.15) / comfort))
    shown = ctx["shown"].get(item["id"], 0)
    if shown > SKIP_FREE and item["status"] != "in_progress":
        out["skipped"] = max(SKIP_FLOOR, -SKIP_STEP * (shown - SKIP_FREE))
    item["_due_words"] = sum(1 for lex in ctx["learning"].get(item["id"], []) if ctx["due"].get(lex, 0) >= 0.5)
    item["_teach"] = share if unknown >= 3 and not item["estimated"] else None
    return out


def context(conn: Connection, lang: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    ids = [i["id"] for i in items]
    measured = [i["id"] for i in items if not i["estimated"]]
    due = due_words(conn, lang)
    return {
        "due": due,
        "learning": learning_in(conn, measured, set(due)),
        "teach": teach_shares(conn, measured),
        "comfort": comfort_wpm(conn, lang),
        "shown": impressions(conn, ids),
    }


def boost(item: dict[str, Any], ctx: dict[str, Any]) -> float:
    contributions = parts(item, ctx)
    item["_parts"] = {k: round(v, 3) for k, v in contributions.items() if v}
    return math.exp(sum(WEIGHTS[k] * v for k, v in contributions.items()))


# ------------------------------------------------------------------ variety


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


def diversify(items: list[dict[str, Any]], score_of, vectors: dict[int, dict[int, float]]) -> list[dict[str, Any]]:  # noqa: ANN001
    """Re-rank the best ones for variety (maximal marginal relevance over a short window); the rest keep their order."""
    head, tail = items[:MMR_TOP], items[MMR_TOP:]
    out: list[dict[str, Any]] = []
    while head:
        recent = out[-MMR_WINDOW:]
        best_index, best_value = 0, -math.inf
        for index, item in enumerate(head[:MMR_LOOKAHEAD]):
            penalty = max((similarity(item, other, vectors) for other in recent), default=0.0)
            value = math.log(max(score_of(item), 1e-6)) - MMR_LAMBDA * penalty
            if value > best_value:
                best_index, best_value = index, value
        out.append(head.pop(best_index))
    return out + tail


# ------------------------------------------------------------------ today: the time you have left


def time_fit(item: dict[str, Any], minutes_left: float | None) -> float:
    """×1.15 for what fits in the minutes left today, ×0.8 for what's more than twice as long."""
    if not minutes_left or minutes_left < 5:
        return 1.0
    if item.get("duration_sec"):
        minutes = item["duration_sec"] / 60
    elif item.get("word_count"):
        minutes = item["word_count"] / 150
    else:
        return 1.0
    if minutes <= minutes_left * 1.25:
        return 1.15
    return 0.8 if minutes > minutes_left * 2 else 1.0
