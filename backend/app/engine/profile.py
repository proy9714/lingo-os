"""The live User_Proficiency_Profile (proficiency_profiles) and its starting point from hours."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import Connection, text

from app.engine import exams
from app.config import AppConfig
from app.engine.evidence import blend_with_hours, content_evidence
from app.engine.vocab_model import DEFAULT_K, solve_r50
from app.services.estimate import hours_estimate
from app.timeutil import to_iso, utc_now

TESTED_CONFIDENCE = 0.6  # profiles at or above this came from a measurement, not hours


def band_for_size(baselines: dict[str, Any], lang: str, size: float) -> tuple[str | None, str | None]:
    """Approximate CEFR band (and JLPT for Japanese) for a receptive vocabulary size."""
    bands = baselines.get("vocab_bands") or {}

    def pick(table: list[list[Any]]) -> str | None:
        label = None
        for threshold, name in table or []:
            if size >= threshold:
                label = name
        return label

    from app.languages.registry import get

    spec = get(lang)
    alt = spec.level_alt if spec else None
    return pick(bands.get("cefr")), pick(bands.get(alt)) if alt else None


def total_seconds(conn: Connection, lang: str) -> int:
    return int(
        conn.execute(
            text("SELECT COALESCE(SUM(active_seconds), 0) FROM activity_sessions WHERE language_code = :l"), {"l": lang}
        ).scalar_one()
    )


def get_profile(conn: Connection, lang: str) -> dict[str, Any] | None:
    row = conn.execute(
        text(
            "SELECT language_code, version, vocab_r50, vocab_k, est_vocab_size, est_level, est_level_alt, "
            "level_confidence, read_cov_min, read_cov_max, listen_cov_min, listen_cov_max, updated_at "
            "FROM proficiency_profiles WHERE language_code = :l"
        ),
        {"l": lang},
    ).first()
    if not row:
        return None
    keys = (
        "language", "version", "r50", "k", "vocab_size", "level", "level_alt", "confidence",
        "read_cov_min", "read_cov_max", "listen_cov_min", "listen_cov_max", "updated_at",
    )
    profile = dict(zip(keys, row))
    profile["measured"] = profile["confidence"] >= TESTED_CONFIDENCE
    return profile


# A level you chose yourself (when adding the language, or in Settings), as a receptive vocabulary: the middle of the
# usual range for that level. It replaces the hours-only guess until a Level Lab test measures you.
SELF_LEVEL_WORDS = {
    "A0": 100, "A1": 600, "A2": 1500, "B1": 2700, "B2": 4700, "C1": 8000, "C2": 12000,
    "N5": 1000, "N4": 2200, "N3": 4500, "N2": 7500, "N1": 11000,
}


def self_level(conn: Connection, lang: str) -> str | None:
    from app.db import settings_store

    value = settings_store.get(conn, f"self_level.{lang}")
    return value if value in SELF_LEVEL_WORDS else None


def exam_result(conn: Connection, lang: str) -> dict[str, Any] | None:
    from app.db import settings_store

    value = settings_store.get(conn, f"exam.{lang}")
    return value if isinstance(value, dict) and value.get("level") in SELF_LEVEL_WORDS else None


def chosen_start(conn: Connection, lang: str) -> tuple[int, str] | None:
    """The words implied by a passed (recent) exam or else the level you chose, with a label; None if neither."""
    exam = exam_result(conn, lang)
    if exam and exams.weight(exam.get("passed_on")) > 0:
        return SELF_LEVEL_WORDS[exam["level"]], f"{exam.get('name') or 'exam'} {exam.get('label') or exam['level']}"
    chosen = self_level(conn, lang)
    return (SELF_LEVEL_WORDS[chosen], chosen) if chosen else None


def starting_estimate(conn: Connection, cfg: AppConfig, lang: str) -> dict[str, Any]:
    """The roadmap estimate from your hours, moved up to the level you chose (or passed) when that is further."""
    start = chosen_start(conn, lang)
    return hours_estimate(
        lang,
        total_seconds(conn, lang) / 3600,
        cfg.baselines,
        start_words=start[0] if start else None,
        start_label=start[1] if start else None,
    )


def sync_baselines(conn: Connection, cfg: AppConfig) -> None:
    """Create missing profiles; refresh untested ones from current hours (after an import, say)."""
    for lang in cfg.language_codes:
        sync_language(conn, cfg, lang)


def sync_language(conn: Connection, cfg: AppConfig, lang: str) -> None:
    """The starting estimate for one language: your chosen level, else your hours; blended with what you watched."""
    profile = get_profile(conn, lang)
    if profile and profile["measured"]:
        return
    estimate = hours_estimate(lang, total_seconds(conn, lang) / 3600, cfg.baselines)
    hours_words = max(100, estimate.get("words_prior") or 100)
    chosen = self_level(conn, lang)
    if chosen:
        hours_words = SELF_LEVEL_WORDS[chosen]
    exam = exam_result(conn, lang)
    exam_weight = exams.weight(exam.get("passed_on")) if exam else 0.0
    if exam and exam_weight > 0:  # a passed exam outranks a level you chose, until it's old
        hours_words = SELF_LEVEL_WORDS[exam["level"]]
    words, confidence = blend_with_hours(hours_words, content_evidence(conn, lang))
    if exam_weight > 0:
        confidence = round(max(confidence, confidence + (exams.EXAM_CONFIDENCE - confidence) * exam_weight), 3)
    words = round(words)
    r50 = solve_r50(words, DEFAULT_K)
    level, alt = band_for_size(cfg.baselines, lang, words)
    if profile and abs(profile["vocab_size"] - words) < 5 and abs(profile["confidence"] - confidence) < 0.01:
        return
    reason = "exam" if exam_weight > 0 else "baseline" if confidence <= 0.2 else "recompute"
    _write(conn, lang, r50=r50, k=DEFAULT_K, size=words, level=level, alt=alt, confidence=confidence, reason=reason)


def apply_measurement(
    conn: Connection, cfg: AppConfig, lang: str, *, r50: float, k: float, size: float, reason: str = "assessment"
) -> dict[str, Any]:
    level, alt = band_for_size(cfg.baselines, lang, size)
    _write(conn, lang, r50=r50, k=k, size=size, level=level, alt=alt, confidence=TESTED_CONFIDENCE, reason=reason)
    return get_profile(conn, lang) or {}


def _write(
    conn: Connection,
    lang: str,
    *,
    r50: float,
    k: float,
    size: float,
    level: str | None,
    alt: str | None,
    confidence: float,
    reason: str,
) -> None:
    now = to_iso(utc_now())
    existing = get_profile(conn, lang)
    version = (existing["version"] + 1) if existing else 1
    document = {
        "language": lang,
        "version": version,
        "updated_at": now,
        "level": {"cefr": level, "jlpt": alt, "confidence": confidence, "basis": reason},
        "vocabulary": {"estimated_size": round(size), "model": {"r50": round(r50, 1), "k": k}},
    }
    conn.execute(
        text(
            "INSERT INTO proficiency_profiles (language_code, version, vocab_r50, vocab_k, est_vocab_size, est_level, "
            "est_level_alt, level_confidence, profile_json, updated_at) VALUES (:l, :v, :r50, :k, :size, :lvl, :alt, "
            ":conf, :doc, :now) ON CONFLICT(language_code) DO UPDATE SET version = excluded.version, "
            "vocab_r50 = excluded.vocab_r50, vocab_k = excluded.vocab_k, est_vocab_size = excluded.est_vocab_size, "
            "est_level = excluded.est_level, est_level_alt = excluded.est_level_alt, "
            "level_confidence = excluded.level_confidence, profile_json = excluded.profile_json, "
            "updated_at = excluded.updated_at"
        ),
        {
            "l": lang, "v": version, "r50": r50, "k": k, "size": int(round(size)), "lvl": level, "alt": alt,
            "conf": confidence, "doc": json.dumps(document), "now": now,
        },
    )
    conn.execute(
        text(
            "INSERT OR IGNORE INTO profile_snapshots (language_code, profile_version, reason, profile_json) "
            "VALUES (:l, :v, :reason, :doc)"
        ),
        {"l": lang, "v": version, "reason": reason, "doc": json.dumps(document)},
    )
