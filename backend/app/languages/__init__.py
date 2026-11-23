"""Language packs: turn text into tokens with lemmas, readings and parts of speech.

One pack per language, loaded lazily (spaCy and MeCab models take a moment).
Adding a language = one module implementing `LanguagePack` + one entry in `_FACTORIES`.
"""

from __future__ import annotations

from functools import lru_cache
from importlib import import_module

from app.languages.base import LanguagePack, Sentence, Token

_FACTORIES = {
    "de": ("app.languages.de", "GermanPack"),
    "es": ("app.languages.es", "SpanishPack"),
    "ja": ("app.languages.ja", "JapanesePack"),
}


class UnsupportedLanguage(ValueError):
    pass


@lru_cache(maxsize=None)
def get_pack(code: str) -> LanguagePack:
    if code not in _FACTORIES:
        raise UnsupportedLanguage(f"no language pack for '{code}'")
    module_name, class_name = _FACTORIES[code]
    return getattr(import_module(module_name), class_name)()


@lru_cache(maxsize=256)
def analyze(code: str, text: str) -> tuple[tuple[Token, ...], tuple[Sentence, ...]]:
    tokens, sentences = get_pack(code).analyze(text)
    return tuple(tokens), tuple(sentences)


__all__ = ["LanguagePack", "Sentence", "Token", "UnsupportedLanguage", "analyze", "get_pack"]
