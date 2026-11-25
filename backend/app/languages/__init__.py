"""Language packs: turn text into tokens with lemmas, readings and parts of speech.

One pack per language, loaded lazily (spaCy and MeCab models take a moment). Which pack a language uses is set in
`registry.py`; adding a language = one catalogue entry, plus a pack module if spaCy's generic one doesn't fit.
"""

from __future__ import annotations

import dataclasses
from functools import lru_cache
from typing import Callable

from app.languages.base import LanguagePack, Sentence, Token
from app.languages.spacy_pack import ModelMissing


class UnsupportedLanguage(ValueError):
    pass


def _build(code: str) -> LanguagePack:
    from app.languages import registry

    s = registry.get(code)
    if s is None or code not in registry.AVAILABLE:
        raise UnsupportedLanguage(f"no language pack for '{code}'")
    if s.pack == "de":
        from app.languages.de import GermanPack

        return GermanPack()
    if s.pack == "es":
        from app.languages.es import SpanishPack

        return SpanishPack()
    if s.pack == "ja":
        from app.languages.ja import JapanesePack

        return JapanesePack()
    if s.pack == "ko":
        from app.languages.spacy_pack import KoreanPack

        return KoreanPack()
    if s.pack == "zh":
        from app.languages.spacy_pack import ChinesePack

        return ChinesePack()
    if s.pack in {"hi", "bn", "ar"}:
        from app.languages.script_pack import ScriptPack

        return ScriptPack(code)
    if s.pack == "spacy" and s.model:
        from app.languages.spacy_pack import SpacyPack

        return SpacyPack(code, s.model.name)
    raise UnsupportedLanguage(f"no language pack for '{code}'")


@lru_cache(maxsize=None)
def get_pack(code: str) -> LanguagePack:
    return _build(code)


# Some models guess lemmas badly (Italian "chiamo" → "chare"). For those languages, a lemma that isn't a dictionary
# headword is replaced by what the dictionary says the word is a form of. Set at startup (main.bootstrap).
LemmaResolver = Callable[[str, str, str], str | None]
_resolver: list[LemmaResolver] = []


def set_lemma_resolver(resolver: LemmaResolver | None) -> None:
    _resolver.clear()
    if resolver:
        _resolver.append(resolver)
    analyze.cache_clear()


def _repair(code: str, tokens: list[Token]) -> list[Token]:
    from app.languages import registry

    s = registry.get(code)
    if not (_resolver and s and s.dictionary_lemmas):
        return tokens
    from app.languages.script_pack import guessed_forms, strip_marks

    out = []
    for token in tokens:
        if token.is_word and token.lemma:
            others = tuple(f for f in token.lookup_forms if f != token.lemma)
            better = _resolver[0](code, strip_marks(code, token.text.lower()), token.lemma, others, guessed_forms(code, token.text))
            if better and better != token.lemma:
                token = dataclasses.replace(token, lemma=better, lookup_forms=tuple(dict.fromkeys((*token.lookup_forms, better))))
        out.append(token)
    return out


@lru_cache(maxsize=256)
def analyze(code: str, text: str) -> tuple[tuple[Token, ...], tuple[Sentence, ...]]:
    tokens, sentences = get_pack(code).analyze(text)
    return tuple(_repair(code, tokens)), tuple(sentences)


def forget_pack(code: str | None = None) -> None:
    """After a model is downloaded: build the pack again on next use."""
    get_pack.cache_clear()
    analyze.cache_clear()


__all__ = [
    "LanguagePack", "ModelMissing", "Sentence", "Token", "UnsupportedLanguage", "analyze", "forget_pack", "get_pack",
    "set_lemma_resolver",
]
