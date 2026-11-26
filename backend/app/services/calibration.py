"""How hard is "just right" for you? Learned from your difficulty ratings (very easy … very hard).

Every item has a measured coverage (the share of its running words you probably know). A rating says where that
coverage sits for you: "very easy" at 96% means you can take harder things (your ideal is lower), "very hard" at 88%
means you need easier ones (your ideal is higher). Each rating implies an ideal coverage; the estimate is their
weighted mean, recent ratings counting more, pulled toward the default until there are a few ratings.
Videos (listening) and reading are calibrated separately: the same coverage feels harder by ear.

The level window (stretch / just right / comfortable …) used to score every item is centred on this ideal, plus the
small weekly shift from the review (evolve.band_shift).
"""

from __future__ import annotations

import math
from typing import Any

from sqlalchemy import Connection, text

from app.db import settings_store
from app.timeutil import from_iso, to_iso, utc_now

LABELS = {1: "Very easy", 2: "Easy", 3: "Comfortable", 4: "Hard", 5: "Very hard"}
# where your ideal coverage sits relative to an item you gave this rating
IMPLIED_OFFSET = {1: -0.06, 2: -0.03, 3: 0.0, 4: 0.03, 5: 0.06}
DEFAULT_IDEAL = {"listening": 0.925, "reading": 0.90}
WIDTH = {"listening": 0.09, "reading": 0.10}  # width of the "just right" window
PRIOR_WEIGHT = 2.0
HALF_LIFE_DAYS = 90.0
IDEAL_RANGE = (0.72, 0.985)

WATCH_TYPES = {"youtube", "video", "audio", "podcast_episode"}


def modality_of(item_type: str) -> str:
    return "listening" if item_type in WATCH_TYPES else "reading"


def ratings(conn: Connection, lang: str, modality: str | None = None) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            "SELECT ci.id, ci.type, ci.title, ci.perceived_difficulty, cs.coverage, "
            "COALESCE(json_extract(ci.metadata_json, '$.rated_at'), ci.last_opened_at, ci.added_at) "
            "FROM content_items ci JOIN content_scores cs ON cs.content_item_id = ci.id "
            "WHERE ci.language_code = :l AND ci.perceived_difficulty IS NOT NULL AND cs.estimated = 0"
        ),
        {"l": lang},
    ).all()
    out = [
        {"id": r[0], "type": r[1], "title": r[2], "rating": r[3], "coverage": r[4], "rated_at": r[5], "modality": modality_of(r[1])}
        for r in rows
    ]
    return [r for r in out if modality in (None, r["modality"])]


def estimate_ideal(conn: Connection, lang: str, modality: str) -> dict[str, Any]:
    now = utc_now()
    total_w = PRIOR_WEIGHT
    total = PRIOR_WEIGHT * DEFAULT_IDEAL[modality]
    rated = ratings(conn, lang, modality)
    for r in rated:
        age_days = max(0.0, (now - from_iso(r["rated_at"])).total_seconds() / 86400) if r["rated_at"] else 0.0
        w = 0.5 ** (age_days / HALF_LIFE_DAYS)
        total += w * (r["coverage"] + IMPLIED_OFFSET[r["rating"]])
        total_w += w
    ideal = min(IDEAL_RANGE[1], max(IDEAL_RANGE[0], total / total_w))
    return {"modality": modality, "ideal": round(ideal, 4), "default": DEFAULT_IDEAL[modality], "ratings": len(rated)}


def _key(lang: str, modality: str) -> str:
    return f"calibration.{lang}.{modality}"


def ideal(conn: Connection, lang: str, modality: str) -> float:
    stored = settings_store.get(conn, _key(lang, modality))
    return float(stored) if stored is not None else DEFAULT_IDEAL[modality]


def recalibrate(conn: Connection, lang: str) -> dict[str, Any]:
    out = {}
    for modality in DEFAULT_IDEAL:
        result = estimate_ideal(conn, lang, modality)
        settings_store.put(conn, _key(lang, modality), result["ideal"])
        out[modality] = result
    return out


def window(conn: Connection, lang: str, item_type: str) -> tuple[float, float]:
    """(lo, hi) coverage of the "just right" band for this kind of item."""
    modality = modality_of(item_type)
    shift = float(settings_store.get(conn, f"band_shift.{lang}", 0.0) or 0.0)  # weekly review
    centre = ideal(conn, lang, modality) + shift
    half = WIDTH[modality] / 2
    return centre - half, centre + half


EASY_SIDE = 1.6  # the fit falls off this much more slowly above the ideal (easier) than below it (harder)


def band_and_fit(coverage: float, lo: float, hi: float) -> tuple[str, float]:
    """The band an item falls in, and how well it fits (1 at your ideal coverage).

    The fit curve is lopsided on purpose: something a little easier than ideal is still pleasant and you still learn
    from it, while something a little harder is tiring and you learn less (too many unknown words to work them out
    from context). So each step of coverage above the ideal costs less than the same step below it."""
    centre, width = (lo + hi) / 2, hi - lo
    band = (
        "too_hard" if coverage < lo - 0.1 else "stretch" if coverage < lo else "i_plus_1" if coverage <= hi
        else "comfortable" if coverage <= hi + 0.02 else "too_easy"
    )
    spread = width * (EASY_SIDE if coverage > centre else 1.0)
    return band, round(math.exp(-(((coverage - centre) / spread) ** 2)), 4)


def summary(conn: Connection, lang: str) -> dict[str, Any]:
    out = {}
    for modality in DEFAULT_IDEAL:
        rated = ratings(conn, lang, modality)
        out[modality] = {
            "ideal": ideal(conn, lang, modality),
            "default": DEFAULT_IDEAL[modality],
            "ratings": len(rated),
            "counts": {LABELS[n]: sum(1 for r in rated if r["rating"] == n) for n in LABELS},
        }
    return out


def reband(conn: Connection, lang: str) -> int:
    """Re-label every measured item for the current window. Fast: coverage is kept, only band and fit change."""
    windows = {m: window(conn, lang, "youtube" if m == "listening" else "text") for m in DEFAULT_IDEAL}
    rows = conn.execute(
        text(
            "SELECT cs.content_item_id, ci.type, cs.coverage FROM content_scores cs JOIN content_items ci "
            "ON ci.id = cs.content_item_id WHERE ci.language_code = :l AND cs.estimated = 0"
        ),
        {"l": lang},
    ).all()
    for item_id, item_type, coverage in rows:
        band, fit = band_and_fit(coverage, *windows[modality_of(item_type)])
        conn.execute(
            text("UPDATE content_scores SET band = :b, i1_score = :s WHERE content_item_id = :i"),
            {"b": band, "s": fit, "i": item_id},
        )
    return len(rows)


def rate(conn: Connection, item_id: int, value: int | None) -> dict[str, Any]:
    """Store your difficulty rating for an item and recalibrate. Returns what changed, in plain words."""
    from app.services import catalog, content

    item = content.get_item(conn, item_id)
    lang, modality = item["language"], modality_of(item["type"])
    before = ideal(conn, lang, modality)
    conn.execute(text("UPDATE content_items SET perceived_difficulty = :v WHERE id = :i"), {"v": value, "i": item_id})
    content.set_metadata(conn, item_id, rated_at=to_iso(utc_now()))
    after = recalibrate(conn, lang)[modality]
    reband(conn, lang)
    catalog.estimate_scores(conn, lang)
    delta = after["ideal"] - before
    noun = "videos" if modality == "listening" else "reading"
    if item["coverage"] is None:
        message = "Saved. Ratings tune your suggestions once an item has been analysed."
    elif abs(delta) < 0.002:
        message = f"Saved. Your {noun} level stays where it was."
    elif delta > 0:
        message = f"Saved. Suggested {noun} will be a little easier."
    else:
        message = f"Saved. Suggested {noun} will be a little harder."
    return {
        "id": item_id,
        "value": value,
        "label": LABELS.get(value) if value else None,
        "modality": modality,
        "ideal_before": round(before, 4),
        "ideal_after": after["ideal"],
        "ratings": after["ratings"],
        "message": message,
    }
