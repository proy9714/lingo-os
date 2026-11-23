"""AI explanations in the lookup panel: a word's meaning in its sentence, and a sentence's grammar."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import Connection, text

from app.ai.gateway import Gateway
from app.dictionary.lookup import lookup as dict_lookup
from app.engine.profile import get_profile

LANGUAGE_NAMES = {"de": "German", "es": "Spanish", "ja": "Japanese"}
MAX_SENSES = 8


class ContextGloss(BaseModel):
    meaning: str
    sense: int = -1
    note: str = ""
    translation: str = ""


class GrammarPart(BaseModel):
    text: str
    gloss: str = ""
    role: str = ""


class GrammarPoint(BaseModel):
    name: str
    explanation: str
    level: str = ""


class GrammarBreakdown(BaseModel):
    translation: str
    literal: str = ""
    parts: list[GrammarPart] = Field(default_factory=list)
    points: list[GrammarPoint] = Field(default_factory=list)


def _language_name(conn: Connection, lang: str) -> str:
    name = conn.execute(text("SELECT name FROM languages WHERE code = :c"), {"c": lang}).scalar()
    return name or LANGUAGE_NAMES.get(lang, lang)


def dictionary_senses(dict_conn: Connection, lang: str, lemma: str, surface: str, reading: str) -> list[str]:
    result = dict_lookup(dict_conn, lang, list(dict.fromkeys([lemma, surface])), reading)
    senses: list[str] = []
    for entry in result["entries"][:3]:
        for gloss in entry["glosses"][:4]:
            if gloss not in senses:
                senses.append(gloss)
    return senses[:MAX_SENSES]


def context_gloss(
    gateway: Gateway,
    conn: Connection,
    dict_conn: Connection,
    *,
    lang: str,
    sentence: str,
    surface: str,
    lemma: str,
    pos: str,
    reading: str,
) -> dict[str, Any]:
    senses = dictionary_senses(dict_conn, lang, lemma, surface, reading)
    variables = {
        "language": _language_name(conn, lang),
        "sentence": sentence.strip(),
        "surface": surface,
        "lemma": lemma,
        "pos": pos.lower() or "unknown",
        "senses": "\n".join(f"{i}: {s}" for i, s in enumerate(senses)) or "(none found)",
    }
    result, meta = gateway.structured("lookup.context_gloss", "context_gloss", variables, ContextGloss)
    fitting = senses[result.sense] if 0 <= result.sense < len(senses) else None
    return {**result.model_dump(), "fitting_sense": fitting, **meta}


def grammar_breakdown(gateway: Gateway, conn: Connection, *, lang: str, sentence: str) -> dict[str, Any]:
    profile = get_profile(conn, lang) or {}
    variables = {
        "language": _language_name(conn, lang),
        "sentence": sentence.strip(),
        "level": profile.get("level") or ("N4" if lang == "ja" else "B1"),
    }
    result, meta = gateway.structured("lookup.grammar", "grammar", variables, GrammarBreakdown)
    # Keep only chunks that really occur in the sentence, so the UI can underline them.
    parts = [p for p in result.parts if p.text and p.text in sentence]
    return {**result.model_dump(), "parts": [p.model_dump() for p in parts], "points": [p.model_dump() for p in result.points[:3]], **meta}
