"""Official language exams: a passed exam anchors the starting estimate more firmly than a level you chose yourself.

Each exam level maps to a CEFR level (or JLPT for Japanese) and so to a receptive vocabulary (profile.SELF_LEVEL_WORDS).
An exam counts for less as it ages: after two years without it being refreshed, it weighs like a self-assessment.
A Level Lab test still overrides it, because it measures you now.
"""

from __future__ import annotations

from datetime import date
from typing import Any

EXAM_CONFIDENCE = 0.45  # between a self-assessment (0.2) and a Level Lab measurement (0.6)
FADES_AFTER_DAYS = 730

_CEFR = ("A1", "A2", "B1", "B2", "C1", "C2")


def _cefr_levels(prefix: str = "", levels: tuple[str, ...] = _CEFR) -> list[dict[str, str]]:
    return [{"id": level, "label": f"{prefix}{level}", "level": level} for level in levels]


def _numbered(name: str, mapping: list[tuple[str, str]]) -> list[dict[str, str]]:
    return [{"id": n, "label": f"{name} {n}", "level": level} for n, level in mapping]


EXAMS: dict[str, list[dict[str, Any]]] = {
    "de": [
        {"id": "goethe", "name": "Goethe-Zertifikat", "levels": _cefr_levels()},
        {"id": "telc", "name": "telc Deutsch", "levels": _cefr_levels()},
        {"id": "oesd", "name": "ÖSD", "levels": _cefr_levels()},
        {"id": "testdaf", "name": "TestDaF", "levels": _numbered("TDN", [("3", "B2"), ("4", "C1"), ("5", "C1")])},
    ],
    "es": [
        {"id": "dele", "name": "DELE", "levels": _cefr_levels()},
        {"id": "siele", "name": "SIELE", "levels": _cefr_levels(levels=("A1", "A2", "B1", "B2", "C1"))},
    ],
    "fr": [
        {"id": "delf", "name": "DELF / DALF", "levels": _cefr_levels()},
        {"id": "tcf", "name": "TCF", "levels": _cefr_levels()},
    ],
    "it": [
        {"id": "celi", "name": "CELI", "levels": _cefr_levels()},
        {"id": "cils", "name": "CILS", "levels": _cefr_levels()},
        {"id": "plida", "name": "PLIDA", "levels": _cefr_levels()},
    ],
    "pt": [
        {"id": "caple", "name": "CAPLE", "levels": _cefr_levels()},
        {"id": "celpe", "name": "Celpe-Bras", "levels": [
            {"id": "intermediario", "label": "Intermediário", "level": "B1"},
            {"id": "intermediario-superior", "label": "Intermediário Superior", "level": "B2"},
            {"id": "avancado", "label": "Avançado", "level": "C1"},
            {"id": "avancado-superior", "label": "Avançado Superior", "level": "C2"},
        ]},
    ],
    "ru": [
        {"id": "torfl", "name": "TORFL (ТРКИ)", "levels": [
            {"id": "a1", "label": "Elementary (ТЭУ)", "level": "A1"}, {"id": "a2", "label": "Basic (ТБУ)", "level": "A2"},
            {"id": "b1", "label": "ТРКИ-1", "level": "B1"}, {"id": "b2", "label": "ТРКИ-2", "level": "B2"},
            {"id": "c1", "label": "ТРКИ-3", "level": "C1"}, {"id": "c2", "label": "ТРКИ-4", "level": "C2"},
        ]},
    ],
    "ja": [
        {"id": "jlpt", "name": "JLPT", "levels": [{"id": n, "label": n, "level": n} for n in ("N5", "N4", "N3", "N2", "N1")]},
    ],
    "ko": [
        {"id": "topik", "name": "TOPIK", "levels": _numbered("Level", [("1", "A1"), ("2", "A2"), ("3", "B1"), ("4", "B2"), ("5", "C1"), ("6", "C2")])},
    ],
    "zh": [
        {"id": "hsk", "name": "HSK", "levels": _numbered("HSK", [("1", "A1"), ("2", "A1"), ("3", "A2"), ("4", "B1"), ("5", "B2"), ("6", "C1")])},
    ],
}
# Any language: a certificate with a CEFR level (school, university, another body)
OTHER = {"id": "other", "name": "Another certificate (CEFR level)", "levels": _cefr_levels()}


def catalogue(lang: str) -> list[dict[str, Any]]:
    return [*EXAMS.get(lang, []), OTHER]


def resolve(lang: str, exam: str, level: str) -> dict[str, str]:
    """The exam and level as stored, or ValueError if this language has no such exam or level."""
    found = next((e for e in catalogue(lang) if e["id"] == exam), None)
    if not found:
        raise ValueError(f"unknown exam '{exam}' for {lang}")
    step = next((lv for lv in found["levels"] if lv["id"] == level), None)
    if not step:
        raise ValueError(f"{found['name']} has no level '{level}'")
    return {"exam": exam, "name": found["name"], "level_id": level, "label": step["label"], "level": step["level"]}


def weight(passed_on: str | None, today: date | None = None) -> float:
    """How much an exam still counts: full for two years, then fading to a self-assessment's weight over a year."""
    if not passed_on:
        return 1.0
    try:
        age = ((today or date.today()) - date.fromisoformat(passed_on[:10])).days
    except ValueError:
        return 1.0
    if age <= FADES_AFTER_DAYS:
        return 1.0
    return max(0.0, 1 - (age - FADES_AFTER_DAYS) / 365)
