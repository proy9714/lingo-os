"""Import a Yomitan dictionary zip into dictionaries.db.

Only JSON entries are read from the zip, in memory; nothing is extracted to disk.
Re-importing a dictionary with the same title replaces the old copy.
"""

from __future__ import annotations

import json
import re
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, text

from app.dictionary.structured import compact

TERM_BANK = re.compile(r"^term_bank_\d+\.json$")
BATCH = 5000


class NotAYomitanDictionary(ValueError):
    pass


def read_index(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path) as archive:
        try:
            index = json.loads(archive.read("index.json"))
        except KeyError as exc:
            raise NotAYomitanDictionary(f"{path.name} has no index.json") from exc
    if index.get("format", index.get("version")) not in (1, 2, 3):
        raise NotAYomitanDictionary(f"{path.name}: unsupported Yomitan format {index.get('format')}")
    return index


def import_dictionary(
    conn: Connection,
    path: Path,
    *,
    language: str | None = None,
    priority: int = 100,
    progress: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    index = read_index(path)
    lang = language or index.get("sourceLanguage")
    if not lang:
        raise NotAYomitanDictionary(f"{path.name}: no sourceLanguage in index.json; pass the language explicitly")
    title = index.get("title") or path.stem

    # Replace any earlier copy of this dictionary (any revision).
    conn.execute(text("DELETE FROM dictionaries WHERE language_code = :l AND name = :n"), {"l": lang, "n": _name(title)})
    dictionary_id = conn.execute(
        text(
            "INSERT INTO dictionaries (language_code, name, kind, format, revision, attribution, source_path, priority) "
            "VALUES (:l, :n, 'term', 'yomitan', :rev, :attr, :src, :prio)"
        ),
        {
            "l": lang,
            "n": _name(title),
            "rev": str(index.get("revision", "")),
            "attr": index.get("attribution") or index.get("url") or "",
            "src": path.name,
            "prio": priority,
        },
    ).lastrowid

    total = forms = skipped = 0
    with zipfile.ZipFile(path) as archive:
        banks = sorted((n for n in archive.namelist() if TERM_BANK.match(n)), key=lambda n: int(re.sub(r"\D", "", n)))
        for bank_number, bank in enumerate(banks, start=1):
            rows = json.loads(archive.read(bank))
            batch = []
            for row in rows:
                term, reading, def_tags, rules, score, glossary = row[0], row[1], row[2] or "", row[3] or "", row[4], row[5]
                data = compact(def_tags, glossary if isinstance(glossary, list) else [glossary])
                if not data["g"] and "f" not in data:
                    skipped += 1
                    continue
                if "f" in data and not data["g"]:
                    forms += 1
                batch.append(
                    {
                        "d": dictionary_id,
                        "t": term,
                        "r": reading or "",
                        "dt": def_tags,
                        "ru": rules,
                        "s": int(score or 0),
                        "g": json.dumps(data, ensure_ascii=False, separators=(",", ":")),
                        "seq": row[6] if len(row) > 6 and isinstance(row[6], int) else None,
                        "tt": row[7] if len(row) > 7 and isinstance(row[7], str) else None,
                    }
                )
                if len(batch) >= BATCH:
                    _insert(conn, batch)
                    total += len(batch)
                    batch = []
            if batch:
                _insert(conn, batch)
                total += len(batch)
            if progress:
                progress(bank_number, len(banks))

    conn.execute(text("UPDATE dictionaries SET entry_count = :c WHERE id = :id"), {"c": total, "id": dictionary_id})
    return {"dictionary": _name(title), "language": lang, "entries": total, "inflected_forms": forms, "skipped": skipped}


def _name(title: str) -> str:
    # 'Jitendex.org [2026-11-23]' → 'Jitendex.org' so new releases replace old ones
    return re.sub(r"\s*\[[^\]]*\]\s*$", "", title).strip() or title


def _insert(conn: Connection, batch: list[dict[str, Any]]) -> None:
    conn.execute(
        text(
            "INSERT INTO dict_terms (dictionary_id, term, reading, definition_tags, rules, score, glossary_json, "
            "sequence, term_tags) VALUES (:d, :t, :r, :dt, :ru, :s, :g, :seq, :tt)"
        ),
        batch,
    )


def list_dictionaries(conn: Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            "SELECT id, language_code, name, revision, entry_count, priority, enabled, source_path, imported_at "
            "FROM dictionaries ORDER BY language_code, priority, name"
        )
    ).all()
    keys = ("id", "language", "name", "revision", "entries", "priority", "enabled", "file", "imported_at")
    return [dict(zip(keys, row)) for row in rows]
