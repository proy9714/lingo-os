from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import Connection, text

from app.api.deps import get_conn, get_dict_conn, require_language
from app.dictionary.lookup import lookup as dict_lookup
from app.dictionary.yomitan import list_dictionaries
from app.services import vocab
from app.services.annotate import MAX_CHARS, annotate, word_info

router = APIRouter(prefix="/api/nlp", tags=["nlp"])


class TokenizeRequest(BaseModel):
    lang: str = Field(min_length=2, max_length=8)
    text: str = Field(min_length=1, max_length=MAX_CHARS)


class LookupRequest(BaseModel):
    lang: str = Field(min_length=2, max_length=8)
    lemma: str = Field(min_length=1, max_length=200)
    reading: str = Field(default="", max_length=200)
    pos: str = Field(default="", max_length=16)
    forms: list[str] = Field(default_factory=list, max_length=16)  # Arabic: with and without prefixes, endings, hamza seats
    record: bool = True  # count it as a lookup (lowers the word's known-probability)


@router.post("/tokenize")
def tokenize(body: TokenizeRequest, conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    require_language(conn, body.lang)
    return annotate(conn, body.lang, body.text)


@router.post("/lookup")
def lookup(
    body: LookupRequest, conn: Connection = Depends(get_conn), dict_conn: Connection = Depends(get_dict_conn)
) -> dict[str, Any]:
    require_language(conn, body.lang)
    forms = list(dict.fromkeys([body.lemma, *body.forms]))
    info = word_info(conn, body.lang, body.lemma, body.reading, forms)
    if body.record:
        state = vocab.record_lookup(conn, body.lang, body.lemma, body.reading, body.pos, info["rank"], info["model_p"])
    else:
        existing = vocab.states(conn, body.lang, [(body.lemma, body.reading)])
        state = next(iter(existing.values()), None)
        state = vocab.word_state(conn, state["lexeme_id"]) if state else None
    result = dict_lookup(dict_conn, body.lang, forms, body.reading)
    if not result["entries"] and not result["inflections"] and not _has_dictionaries(dict_conn, body.lang):
        result["missing_dictionary"] = True
    if not result["entries"] and body.lang == "de":  # a compound the dictionary doesn't list: show its parts
        from app.dictionary.lookup import compound_parts

        for form in forms:
            parts = compound_parts(dict_conn, body.lang, form)
            if parts:
                result["compound"] = parts
                break
    return {
        "lemma": body.lemma,
        "reading": body.reading,
        "pos": body.pos,
        "rank": info["rank"],
        "model_p": info["model_p"],
        "state": state,
        "contexts": vocab.contexts(conn, state["lexeme_id"], limit=3) if state else [],
        **result,
    }


def _has_dictionaries(dict_conn: Connection, lang: str) -> bool:
    return bool(
        dict_conn.execute(text("SELECT 1 FROM dictionaries WHERE language_code = :l AND enabled = 1"), {"l": lang}).first()
    )


@router.get("/dictionaries")
def dictionaries(dict_conn: Connection = Depends(get_dict_conn)) -> list[dict[str, Any]]:
    return list_dictionaries(dict_conn)
