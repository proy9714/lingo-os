"""Is this text in the language being learned? A quick check for search results, with no extra model to download.

Scripts settle Chinese, Japanese, Korean and Russian. Latin-script languages are told apart by their most common
words (spaCy's stop-word lists): a German article is full of "der, und, ist", an English one of "the, and, is".
"""

from __future__ import annotations

import importlib
import re
from functools import lru_cache

LATIN = ("de", "es", "fr", "pt", "it", "en")
# languages sharing a script, told apart by their common words
SAME_SCRIPT = {"hi": ("hi", "mr", "ne"), "ar": ("ar", "fa", "ur")}
SCRIPTS = {
    "hi": r"[ऀ-ॿ]",  # Devanagari
    "bn": r"[ঀ-৿]",  # Bengali
    "ar": r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]",  # Arabic
}
PUNCT = ".,;:!?\"'()[]{}«»“”‘’…–—-।॥،؛؟·"


@lru_cache(maxsize=None)
def _stop_words(code: str) -> frozenset[str]:
    try:
        return frozenset(importlib.import_module(f"spacy.lang.{code}.stop_words").STOP_WORDS)
    except (ImportError, AttributeError):
        return frozenset()


def _share(chars: str, pattern: str) -> float:
    letters = [c for c in chars if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if re.match(pattern, c)) / len(letters)


def looks_like(lang: str, text: str) -> bool:
    """True when `text` reads as `lang`. Too little text to tell counts as yes."""
    sample = text[:6000]
    if sum(1 for c in sample if c.isalpha()) < 40:
        return True
    if lang == "ja":
        return _share(sample, r"[぀-ヿ]") >= 0.08  # kana: only Japanese uses them
    if lang == "zh":
        return _share(sample, r"[一-鿿㐀-䶿]") >= 0.5 and _share(sample, r"[぀-ヿ]") < 0.03
    if lang == "ko":
        return _share(sample, r"[가-힯ᄀ-ᇿ]") >= 0.4
    if lang == "ru":
        return _share(sample, r"[Ѐ-ӿ]") >= 0.5
    if lang in SCRIPTS:
        if _share(sample, SCRIPTS[lang]) < 0.5:
            return False
        return _most_like(lang, sample, SAME_SCRIPT.get(lang, (lang,)), floor=0.08)
    if lang not in LATIN:
        return True  # no check for this language yet
    if _share(sample, r"[A-Za-zÀ-ɏ]") < 0.6:
        return False
    return _most_like(lang, sample, LATIN, floor=0.12)


def _most_like(lang: str, sample: str, rivals: tuple[str, ...], floor: float) -> bool:
    """`lang`'s common words make up at least `floor` of the text, and about as much as any rival language's."""
    # split on spaces, not \w: Hindi and Bengali vowel signs aren't "word" characters to Python's regex
    words = [w.strip(PUNCT).lower() for w in sample.split()]
    words = [w for w in words if w and any(c.isalpha() for c in w)]
    if len(words) < 15 or len(rivals) < 2:
        return True
    shares = {code: sum(1 for w in words if w in _stop_words(code)) / len(words) for code in rivals}
    mine = shares[lang]
    return mine >= floor and mine >= 0.85 * max(shares.values())
