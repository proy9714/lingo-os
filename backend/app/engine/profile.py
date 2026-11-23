"""The live User_Proficiency_Profile (proficiency_profiles) and its starting point from hours."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import Connection, text

from app.config import AppConfig
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

    return pick(bands.get("cefr")), pick(bands.get("jlpt")) if lang == "ja" else None


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


def sync_baselines(conn: Connection, cfg: AppConfig) -> None:
    """Create missing profiles; refresh untested ones from current hours (after an import, say)."""
    for lang in cfg.language_codes:
        profile = get_profile(conn, lang)
        if profile and profile["measured"]:
            continue
        estimate = hours_estimate(lang, total_seconds(conn, lang) / 3600, cfg.baselines)
        words = max(100, estimate.get("words_prior") or 100)
        r50 = solve_r50(words, DEFAULT_K)
        level, alt = band_for_size(cfg.baselines, lang, words)
        if profile and abs(profile["vocab_size"] - words) < 5:
            continue
        _write(conn, lang, r50=r50, k=DEFAULT_K, size=words, level=level, alt=alt, confidence=0.2, reason="baseline")


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
