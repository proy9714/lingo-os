from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class Token:
    text: str
    start: int  # character offsets into the analysed text
    end: int
    is_word: bool  # False for punctuation, numbers, symbols, spaces
    lemma: str = ""  # identity form: 'anrufen', 'comer', '間に合う'
    reading: str = ""  # Japanese reading in hiragana; '' elsewhere
    pos: str = ""  # coarse UPOS-style tag
    learnable: bool = False  # content word worth colouring (not particles, names, numbers…)
    lookup_forms: tuple[str, ...] = field(default=())  # extra dictionary keys (surface, written base form)
    base: str = ""  # dictionary form as written in this text (ご飯 where the lemma is 御飯); defaults to lemma
    ruby: tuple[tuple[str, str], ...] = ()  # Japanese furigana: (text, reading) pieces, reading '' over kana

    @property
    def display(self) -> str:
        return self.base or self.lemma

    @property
    def key(self) -> str:
        return lexeme_key(self.lemma, self.reading)


@dataclass(frozen=True)
class Sentence:
    start: int
    end: int


def lexeme_key(lemma: str, reading: str = "") -> str:
    return f"{lemma}|{reading}"


class LanguagePack(Protocol):
    code: str

    def analyze(self, text: str) -> tuple[list[Token], list[Sentence]]: ...


# Universal POS tags that carry vocabulary worth learning.
LEARNABLE_POS = frozenset({"NOUN", "VERB", "ADJ", "ADV", "INTJ"})
