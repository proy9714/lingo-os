"""Layer 1 of the level estimate (ARCHITECTURE §6.11): hours → roadmap level, adjusted for difficulty.

A level you chose yourself (or a passed exam) moves you along the same roadmap: its vocabulary is turned into the
hours a learner usually needs to get there, and you start from whichever is further, that or your logged hours.
"""

from __future__ import annotations

from typing import Any


def _hours_for_words(roadmap: list[dict[str, Any]], words: float) -> float:
    """Spanish-equivalent hours a learner usually needs to know `words` words (interpolated along the roadmap)."""
    if words <= roadmap[0]["words"]:
        return float(roadmap[0]["hours"])
    for low, high in zip(roadmap, roadmap[1:]):
        if words <= high["words"]:
            span = high["words"] - low["words"]
            share = (words - low["words"]) / span if span else 1.0
            return low["hours"] + share * (high["hours"] - low["hours"])
    return float(roadmap[-1]["hours"])


def hours_estimate(
    language: str,
    total_hours: float,
    baselines: dict[str, Any],
    *,
    start_words: float | None = None,
    start_label: str | None = None,
) -> dict[str, Any]:
    roadmap = sorted(baselines.get("roadmap") or [], key=lambda step: step["hours"])
    if not roadmap:
        return {"basis": "hours only", "confidence": "none", "level": None}
    from app.languages.registry import get

    spec = get(language)
    divisor = float((baselines.get("difficulty_divisor") or {}).get(language) or (spec.divisor if spec else 1.0))
    adjusted = total_hours / divisor
    position, basis = adjusted, "hours only"
    if start_words:
        from_level = _hours_for_words(roadmap, start_words)
        if from_level > adjusted:
            position, basis = from_level, "chosen level"

    current, upcoming = roadmap[0], None
    for index, step in enumerate(roadmap):
        if position >= step["hours"]:
            current = step
            upcoming = roadmap[index + 1] if index + 1 < len(roadmap) else None

    if upcoming:
        span = upcoming["hours"] - current["hours"]
        progress = (position - current["hours"]) / span
        words = current["words"] + progress * (upcoming["words"] - current["words"])
    else:
        progress, words = 1.0, current["words"]
    if basis == "chosen level" and start_words:
        words = start_words

    return {
        "basis": basis,
        "start_label": start_label if basis == "chosen level" else None,
        "confidence": "low",
        "divisor": divisor,
        "adjusted_hours": round(adjusted, 1),
        "position_hours": round(position, 1),
        "level": current["level"],
        "level_label": current["label"],
        "max_level": roadmap[-1]["level"],
        "next_level": upcoming["level"] if upcoming else None,
        "next_level_adjusted_hours": upcoming["hours"] if upcoming else None,
        "hours_to_next_level": round((upcoming["hours"] - position) * divisor, 1) if upcoming else 0.0,
        "progress_to_next": round(progress, 3),
        "words_prior": int(round(words, -1)),
    }
