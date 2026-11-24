"""Dictionary lookups across every enabled dictionary of a language, following inflected forms to lemmas."""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import Connection, bindparam, text

# Leading usage labels in Wiktionary glosses ('vt to make use of', 'lit to call on').
_LABEL_PREFIX = re.compile(r"^(?:(?:v[itr]+|vrvt|lit|fig|rare|obs|dated|archaic|colloq|informal|formal|slang)\b\.?\s+)+", re.I)

_QUERY = text(
    "SELECT d.name, d.priority, t.term, t.reading, t.score, t.glossary_json "
    "FROM dict_terms t JOIN dictionaries d ON d.id = t.dictionary_id "
    "WHERE d.language_code = :lang AND d.enabled = 1 AND t.term IN :terms "
    "ORDER BY d.priority, t.score DESC, t.id LIMIT 60"
).bindparams(bindparam("terms", expanding=True))


def display_gloss(gloss: str, limit: int = 0) -> str:
    gloss = _LABEL_PREFIX.sub("", gloss).strip()
    if limit and len(gloss) > limit:
        cut = max(gloss.rfind(";", 0, limit), gloss.rfind(",", 0, limit))
        gloss = gloss[: cut if cut > limit // 3 else limit].rstrip(" ,;") + ("" if cut > limit // 3 else "…")
    return gloss


def _cased(lang: str) -> bool:
    from app.languages.registry import get

    spec = get(lang)
    return bool(spec and spec.cased)


def _variants(lang: str, forms: list[str]) -> list[str]:
    out: list[str] = []
    for form in forms:
        if not form:
            continue
        out.append(form)
        if _cased(lang):  # German nouns are capitalised, sentence starts are too
            out.extend([form.lower(), form[:1].upper() + form[1:]])
    return list(dict.fromkeys(out))


def _rows(conn: Connection, lang: str, terms: list[str]) -> list[tuple]:
    return conn.execute(_QUERY, {"lang": lang, "terms": terms}).all() if terms else []


def lookup(conn: Connection, lang: str, forms: list[str], reading: str = "", limit: int = 8) -> dict[str, Any]:
    """Entries for the lemma (forms[0]); if it has none, for the other forms. Inflected forms are followed one hop."""
    lemma, others = (forms[0] if forms else ""), [f for f in forms[1:] if f and f != forms[0]]
    primary = _lookup_terms(conn, lang, _variants(lang, [lemma]), reading, limit)
    if not primary["entries"] and others:
        return _lookup_terms(conn, lang, _variants(lang, forms), reading, limit)
    if not any(not e["via_inflection"] for e in primary["entries"]):
        return primary  # the 'lemma' was itself an inflected form: keep its own explanation
    # The lemma has entries: describe only how the clicked form relates to it ('muss' → 'müssen').
    clicked = _lookup_terms(conn, lang, _variants(lang, others), reading, limit) if others else {"inflections": []}
    primary["inflections"] = [i for i in clicked["inflections"] if i["lemma"].lower() == lemma.lower()][:2]
    return primary


def _lookup_terms(conn: Connection, lang: str, terms: list[str], reading: str, limit: int) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    inflections: list[dict[str, Any]] = []
    lemmas_to_follow: list[str] = []

    for name, _prio, term, term_reading, _score, glossary_json in _rows(conn, lang, terms):
        data = json.loads(glossary_json)
        if data.get("g"):
            entries.append(_entry(name, term, term_reading, data))
        for form in data.get("f", []):
            inflections.append({"form": term, "lemma": form["lemma"], "rules": form.get("rules", [])})
            lemmas_to_follow.append(form["lemma"])

    known_terms = {e["term"] for e in entries}
    follow = [lemma for lemma in dict.fromkeys(lemmas_to_follow) if lemma not in known_terms]
    for name, _prio, term, term_reading, _score, glossary_json in _rows(conn, lang, follow):
        data = json.loads(glossary_json)
        if data.get("g"):
            entries.append(_entry(name, term, term_reading, data, via=True))

    # Japanese: entries whose reading matches the token's reading come first.
    if reading:
        entries.sort(key=lambda e: 0 if e["reading"] in {reading, ""} else 1)
    # One entry per (term, reading, first gloss) to avoid duplicates across dictionaries.
    unique: dict[tuple, dict[str, Any]] = {}
    for entry in entries:
        unique.setdefault((entry["term"], entry["reading"], entry["glosses"][0]), entry)
    seen_inflections = {(i["form"], i["lemma"]): i for i in inflections}
    return {"entries": list(unique.values())[:limit], "inflections": list(seen_inflections.values())[:4]}


def _entry(name: str, term: str, reading: str, data: dict[str, Any], via: bool = False) -> dict[str, Any]:
    return {
        "dictionary": name,
        "term": term,
        "reading": reading,
        "pos": data.get("p", []),
        "glosses": [display_gloss(g) for g in data["g"]],
        "note": data.get("n"),
        "via_inflection": via,
    }


def first_gloss(conn: Connection, lang: str, forms: list[str], reading: str = "") -> str | None:
    result = lookup(conn, lang, forms, reading, limit=1)
    return result["entries"][0]["glosses"][0] if result["entries"] else None


def lemma_resolver(engine):  # noqa: ANN001, ANN201 - an Engine on dictionaries.db
    """For language packs whose model guesses lemmas badly: keep a lemma that is a dictionary headword, otherwise
    use the lemma the dictionary gives for the word as written ("chiamo" is a form of "chiamare")."""
    from functools import lru_cache

    @lru_cache(maxsize=50_000)
    def resolve(lang: str, surface: str, lemma: str) -> str | None:
        with engine.connect() as conn:
            rows = _rows(conn, lang, list(dict.fromkeys([lemma.lower(), surface])))
        headwords = {r[2].lower() for r in rows if json.loads(r[5]).get("g")}
        if lemma.lower() in headwords:
            return None
        for row in rows:
            if row[2].lower() != surface:
                continue
            for form in json.loads(row[5]).get("f", []):
                if form.get("lemma"):
                    return form["lemma"].lower()
        return None

    return resolve
