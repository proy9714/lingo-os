"""Spanish: spaCy es_core_news_sm, plus a splitter for pronouns attached to verbs (dámelo → dar)."""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

import spacy

from app.languages.base import LEARNABLE_POS, Sentence, Token

CLITICS = re.compile(r"^(?P<stem>[a-záéíóúñü]{2,}?)(?P<clitics>(?:me|te|se|nos|os|lo|la|los|las|le|les){1,2})$")
VERB_ENDINGS = ("ar", "er", "ir", "ando", "iendo", "yendo")


def _strip_accents(word: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", word) if unicodedata.category(c) != "Mn")


class SpanishPack:
    code = "es"

    def __init__(self) -> None:
        self.nlp = spacy.load("es_core_news_sm", exclude=["ner"])

    @lru_cache(maxsize=4096)
    def _single_lemma(self, word: str) -> tuple[str, str]:
        tok = self.nlp(word)[0]
        return tok.lemma_, tok.pos_

    def _split_clitics(self, word: str) -> str | None:
        """'dámelo' → 'dar', 'aprovecharlo' → 'aprovechar', 'diciéndole' → 'decir'. None if not a verb+clitic form."""
        match = CLITICS.match(word.lower())
        if not match:
            return None
        stem = _strip_accents(match["stem"])
        if stem.endswith(VERB_ENDINGS[:3]):
            return stem
        lemma, pos = self._single_lemma(stem)
        if pos in {"VERB", "AUX"} and lemma.endswith(VERB_ENDINGS[:3]):
            return lemma
        return None

    def analyze(self, text: str) -> tuple[list[Token], list[Sentence]]:
        doc = self.nlp(text)
        tokens: list[Token] = []
        for tok in doc:
            if tok.is_space:
                continue
            is_word = any(ch.isalpha() for ch in tok.text)
            lemma, pos = tok.lemma_, tok.pos_
            if " " in lemma:  # spaCy writes 'aprovecharlo' as 'aprovechar él'
                lemma = lemma.split()[0]
            if is_word and lemma.lower() == tok.text.lower() and pos in {"VERB", "PROPN", "NOUN", "X"}:
                verb = self._split_clitics(tok.text)
                if verb:
                    lemma, pos = verb, "VERB"
            if is_word and pos != "PROPN":
                lemma = lemma.lower()
            tokens.append(
                Token(
                    text=tok.text,
                    start=tok.idx,
                    end=tok.idx + len(tok.text),
                    is_word=is_word,
                    lemma=lemma if is_word else "",
                    pos=pos,
                    learnable=is_word and pos in LEARNABLE_POS,
                    lookup_forms=(tok.text.lower(), tok.lemma_.lower()) if is_word else (),
                )
            )
        return tokens, [Sentence(s.start_char, s.end_char) for s in doc.sents]
