"""Adding and removing languages, and getting each one ready (word-splitting model + dictionary).

Adding a language whose files are already here enables it at once. Otherwise an `install_language` job downloads
them in the background and enables the language when it's done, so it never shows up half-working.
Removing a language only hides it: its words, history and content stay, and adding it again brings them back.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, text

from app.config import AppConfig, forget_added_languages
from app.db import settings_store
from app.languages import registry


class LanguageError(ValueError):
    pass


# ------------------------------------------------------------------ rows


def added_codes(conn: Connection) -> list[str]:
    rows = conn.execute(text("SELECT code FROM languages WHERE enabled = 1 ORDER BY position, rowid")).all()
    return [r[0] for r in rows if registry.get(r[0])]


def add_row(conn: Connection, code: str, variant: str | None) -> None:
    s = registry.spec(code)
    position = (conn.execute(text("SELECT COALESCE(MAX(position), 0) FROM languages WHERE enabled = 1")).scalar() or 0) + 1
    conn.execute(
        text(
            "INSERT INTO languages (code, name, native_name, accent_color, writing_mode, direction, variant, position, enabled) "
            "VALUES (:c, :n, :nn, :a, :w, :d, :v, :p, 1) "
            "ON CONFLICT(code) DO UPDATE SET enabled = 1, variant = COALESCE(excluded.variant, languages.variant), "
            "position = CASE WHEN languages.enabled = 1 THEN languages.position ELSE excluded.position END"
        ),
        {"c": code, "n": s.name, "nn": s.native_name, "a": s.accent, "w": s.writing_mode, "d": s.direction,
         "v": s.variant(variant).id, "p": position},
    )


def refresh_details(conn: Connection) -> None:
    """Keep names, colours and directions in step with the catalogue."""
    for (code,) in conn.execute(text("SELECT code FROM languages")).all():
        s = registry.get(code)
        if s:
            conn.execute(
                text(
                    "UPDATE languages SET name = :n, native_name = :nn, accent_color = :a, writing_mode = :w, direction = :d "
                    "WHERE code = :c"
                ),
                {"c": code, "n": s.name, "nn": s.native_name, "a": s.accent, "w": s.writing_mode, "d": s.direction},
            )


def _enable(conn: Connection, cfg: AppConfig, code: str, variant: str | None) -> None:
    add_row(conn, code, variant)
    goals = settings_store.get(conn, "goals", {}) or {}
    if code not in goals:
        settings_store.put(conn, "goals", {**goals, code: cfg.default_goal_minutes})
    if settings_store.get(conn, "active_language") not in added_codes(conn) or len(added_codes(conn)) == 1:
        settings_store.put(conn, "active_language", code)
    forget_added_languages()


# ------------------------------------------------------------------ readiness


def model_dir(cfg: AppConfig, name: str) -> Path:
    return cfg.data_dir / "models" / name


def model_ready(cfg: AppConfig, code: str) -> bool:
    model = registry.spec(code).model
    if model is None:
        return True
    if (model_dir(cfg, model.name) / "config.cfg").exists():
        return True
    import importlib.util

    return importlib.util.find_spec(model.name) is not None  # installed as a Python package


def dictionaries_of(dict_conn: Connection, code: str) -> list[str]:
    return [r[0] for r in dict_conn.execute(text("SELECT name FROM dictionaries WHERE language_code = :l"), {"l": code}).all()]


def download_mb(cfg: AppConfig, dict_conn: Connection, code: str) -> int:
    s = registry.spec(code)
    size = 0 if model_ready(cfg, code) else (s.model.size_mb if s.model else 0)
    return size + (0 if dictionaries_of(dict_conn, code) else s.dictionary.size_mb)


def install_job(conn: Connection, code: str) -> dict[str, Any] | None:
    row = conn.execute(
        text(
            "SELECT id, status, progress, result_json, error FROM jobs WHERE kind = 'install_language' "
            "AND json_extract(payload_json, '$.code') = :c ORDER BY id DESC LIMIT 1"
        ),
        {"c": code},
    ).first()
    if not row:
        return None
    return {"id": row[0], "status": row[1], "progress": row[2], "result": json.loads(row[3]) if row[3] else None, "error": row[4]}


# ------------------------------------------------------------------ catalogue, add, remove


def catalog(conn: Connection, dict_conn: Connection, cfg: AppConfig) -> list[dict[str, Any]]:
    """Every language Lingo OS can teach, most spoken first, with this learner's state for each."""
    added = added_codes(conn)
    variants = dict(conn.execute(text("SELECT code, variant FROM languages")).all())
    out = []
    for s in registry.CATALOG:
        job = install_job(conn, s.code)
        installing = bool(job and job["status"] in ("queued", "running"))
        out.append(
            {
                "code": s.code, "name": s.name, "native_name": s.native_name, "speakers_millions": s.speakers_millions,
                "accent": s.accent, "accent_ink": s.accent_ink, "direction": s.direction, "script": s.script,
                "available": s.code in registry.AVAILABLE,
                "added": s.code in added,
                "variant": s.variant(variants.get(s.code)).id,
                "variants": [{"id": v.id, "label": v.label} for v in s.variants],
                "download_mb": download_mb(cfg, dict_conn, s.code),
                "has_dictionary": bool(dictionaries_of(dict_conn, s.code)),
                "installing": installing,
                "install": job,
            }
        )
    return out


def add_language(conn: Connection, dict_conn: Connection, cfg: AppConfig, code: str, variant: str | None = None) -> dict[str, Any]:
    from app.jobs.runner import enqueue

    s = registry.get(code)
    if not s:
        raise LanguageError(f"Lingo OS doesn't know the language '{code}'.")
    if code not in registry.AVAILABLE:
        raise LanguageError(f"{s.name} is coming in a later version.")
    if variant and variant not in {v.id for v in s.variants}:
        raise LanguageError(f"{s.name} has no variety '{variant}'.")
    needs_model = not model_ready(cfg, code)
    needs_dictionary = not dictionaries_of(dict_conn, code)
    if not needs_model:
        _enable(conn, cfg, code, variant)
    job = install_job(conn, code)
    if (needs_model or needs_dictionary) and not (job and job["status"] in ("queued", "running")):
        enqueue(conn, "install_language", {"code": code, "variant": variant}, dedupe=False)
    return {"code": code, "added": not needs_model, "installing": needs_model or needs_dictionary}


def remove_language(conn: Connection, code: str) -> dict[str, Any]:
    """Hide a language. Its data stays; adding it again brings it all back."""
    added = added_codes(conn)
    if code not in added:
        raise LanguageError("That language isn't added.")
    if len(added) == 1:
        raise LanguageError("Keep at least one language: add another before removing this one.")
    conn.execute(text("UPDATE languages SET enabled = 0 WHERE code = :c"), {"c": code})
    if settings_store.get(conn, "active_language") == code:
        settings_store.put(conn, "active_language", next(c for c in added if c != code))
    forget_added_languages()
    return {"code": code, "removed": True}


def set_variant(conn: Connection, code: str, variant: str) -> None:
    s = registry.spec(code)
    if variant not in {v.id for v in s.variants}:
        raise LanguageError(f"{s.name} has no variety '{variant}'.")
    conn.execute(text("UPDATE languages SET variant = :v WHERE code = :c"), {"v": variant, "c": code})
    forget_added_languages()


def finish_install(conn: Connection, cfg: AppConfig, code: str, variant: str | None) -> None:
    """Called by the install job once the model is in place."""
    _enable(conn, cfg, code, variant)
