"""The grammar reference for each language (app/grammar/<lang>.yaml), plus links to what the tutor noticed.

Each file is a list of numbered sections: tables (cells "target | translation", several separated by " ;; ",
{…} marks an ending to highlight), a short explanation, and examples [sentence, translation, note, reading].
Sections carry tags; a grammar point the tutor recorded (e.g. "dative after mit") links to the sections whose tags
appear in its name.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import Connection

GRAMMAR_DIR = Path(__file__).resolve().parent.parent / "grammar"
KINDS = {"structure", "verbs", "contrast", "summary"}


class GrammarError(ValueError):
    pass


def available() -> list[str]:
    return sorted(p.stem for p in GRAMMAR_DIR.glob("*.yaml"))


def _check(lang: str, data: dict[str, Any]) -> None:
    seen: set[str] = set()
    for number, section in enumerate(data.get("sections") or [], start=1):
        where = f"{lang} section {number} ({section.get('id')})"
        if not section.get("id") or section["id"] in seen:
            raise GrammarError(f"{where}: missing or repeated id")
        seen.add(section["id"])
        if section.get("kind") not in KINDS:
            raise GrammarError(f"{where}: kind must be one of {sorted(KINDS)}")
        for table in section.get("tables") or []:
            width = len(table.get("head") or [])
            for row in table.get("rows") or []:
                if len(row) != width:
                    raise GrammarError(f"{where}: a table row has {len(row)} cells, the header {width}")
        for example in section.get("examples") or []:
            if not 2 <= len(example) <= 4:
                raise GrammarError(f"{where}: an example needs a sentence and a translation")
        texts = [section.get(k) for k in ("title", "rule", "text", "after", "tip") if section.get(k) is not None]
        texts += list(section.get("points") or []) + [c for e in section.get("examples") or [] for c in e]
        for table in section.get("tables") or []:
            texts += list(table.get("head") or []) + [c for row in table.get("rows") or [] for c in row]
        if any(not isinstance(t, str) for t in texts):  # e.g. an unquoted "a: b" turned into a mapping
            raise GrammarError(f"{where}: every cell and line must be text (quote anything containing ': ')")


@lru_cache(maxsize=8)
def reference(lang: str) -> dict[str, Any]:
    path = GRAMMAR_DIR / f"{lang}.yaml"
    if not path.exists():
        raise GrammarError(f"no grammar reference for '{lang}' yet")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    _check(lang, data)
    sections = []
    for number, section in enumerate(data["sections"], start=1):
        examples = [
            {"text": e[0], "translation": e[1], "note": (e[2] if len(e) > 2 else "") or None, "reading": e[3] if len(e) > 3 else None}
            for e in section.get("examples") or []
        ]
        sections.append(
            {
                "number": number,
                "id": section["id"],
                "title": section["title"],
                "kind": section["kind"],
                "level": str(section.get("level") or ""),
                "tags": [str(t) for t in section.get("tags") or []],
                "rule": section.get("rule"),
                "text": section.get("text"),
                "tables": section.get("tables") or [],
                "after": section.get("after"),
                "examples": examples,
                "points": section.get("points") or [],
                "tip": section.get("tip"),
            }
        )
    return {"language": lang, "title": data.get("title"), "intro": data.get("intro"), "sections": sections}


def _matches(title: str, tags: list[str]) -> bool:
    low = title.casefold()
    words = set(low.replace("-", " ").replace("/", " ").split())
    for tag in tags:
        t = tag.casefold()
        if (" " in t and t in low) or t in words:
            return True
    return False


def weak_spots(conn: Connection, lang: str) -> list[dict[str, Any]]:
    """Grammar points the tutor noticed you still slip on, each with the sections that explain it."""
    from app.services.tutor import grammar_overview

    sections = reference(lang)["sections"]
    out = []
    for point in grammar_overview(conn, lang):
        if point["status"] == "mastered" or (point["mastery"] or 0) >= 0.85:
            continue
        linked = [s["id"] for s in sections if s["kind"] != "summary" and _matches(point["title"], s["tags"])]
        out.append({**point, "sections": linked[:3]})
    return out[:8]
