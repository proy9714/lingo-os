"""Layer 1 of the level estimate (ARCHITECTURE §6.11): hours → roadmap level, adjusted for difficulty."""

from __future__ import annotations

from typing import Any


def hours_estimate(language: str, total_hours: float, baselines: dict[str, Any]) -> dict[str, Any]:
    roadmap = sorted(baselines.get("roadmap") or [], key=lambda step: step["hours"])
    if not roadmap:
        return {"basis": "hours only", "confidence": "none", "level": None}
    from app.languages.registry import get

    spec = get(language)
    divisor = float((baselines.get("difficulty_divisor") or {}).get(language) or (spec.divisor if spec else 1.0))
    adjusted = total_hours / divisor

    current, upcoming = roadmap[0], None
    for index, step in enumerate(roadmap):
        if adjusted >= step["hours"]:
            current = step
            upcoming = roadmap[index + 1] if index + 1 < len(roadmap) else None

    if upcoming:
        span = upcoming["hours"] - current["hours"]
        progress = (adjusted - current["hours"]) / span
        words = current["words"] + progress * (upcoming["words"] - current["words"])
    else:
        progress, words = 1.0, current["words"]

    return {
        "basis": "hours only",
        "confidence": "low",
        "divisor": divisor,
        "adjusted_hours": round(adjusted, 1),
        "level": current["level"],
        "level_label": current["label"],
        "max_level": roadmap[-1]["level"],
        "next_level": upcoming["level"] if upcoming else None,
        "next_level_adjusted_hours": upcoming["hours"] if upcoming else None,
        "hours_to_next_level": round((upcoming["hours"] - adjusted) * divisor, 1) if upcoming else 0.0,
        "progress_to_next": round(progress, 3),
        "words_prior": int(round(words, -1)),
    }
