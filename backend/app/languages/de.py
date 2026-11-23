"""German: spaCy de_core_news_sm, plus separable-verb reattachment and a few lemma fixes."""

from __future__ import annotations

import spacy

from app.languages.base import LEARNABLE_POS, Sentence, Token

# Known slips of the small model's lemmatizer, corrected here (found by probing real text).
LEMMA_FIXES = {
    "mussn": "müssen",
    "musst": "müssen",
    "kannn": "können",
    "darfn": "dürfen",
    "solln": "sollen",
    "wolln": "wollen",
    "mögen": "mögen",
}
PARTICLE_POS = {"ADP", "ADV", "PART", "ADJ"}


class GermanPack:
    code = "de"

    def __init__(self) -> None:
        self.nlp = spacy.load("de_core_news_sm", exclude=["ner"])

    def analyze(self, text: str) -> tuple[list[Token], list[Sentence]]:
        doc = self.nlp(text)
        # "Ich rufe dich morgen an": the particle "an" (dep=svp) belongs to "rufe" → anrufen.
        particle_for_verb = {tok.head.i: tok for tok in doc if tok.dep_ == "svp" and tok.pos_ in PARTICLE_POS}

        tokens: list[Token] = []
        for tok in doc:
            if tok.is_space:
                continue
            is_word = any(ch.isalpha() for ch in tok.text)
            lemma = LEMMA_FIXES.get(tok.lemma_, tok.lemma_) if is_word else tok.text
            if tok.pos_ in {"NOUN"} and lemma[:1].islower():
                lemma = lemma[:1].upper() + lemma[1:]
            pos = tok.pos_
            forms: tuple[str, ...] = (tok.text, tok.text.lower(), tok.lemma_) if is_word else ()
            if tok.i in particle_for_verb:
                lemma = particle_for_verb[tok.i].text.lower() + lemma
                forms = (lemma,)
            elif tok.dep_ == "svp" and tok.pos_ in PARTICLE_POS and tok.head.pos_ in {"VERB", "AUX"}:
                head_lemma = LEMMA_FIXES.get(tok.head.lemma_, tok.head.lemma_)
                lemma, pos = tok.text.lower() + head_lemma, "VERB"
                forms = (lemma,)  # the particle alone ('an') would look up the preposition
            tokens.append(
                Token(
                    text=tok.text,
                    start=tok.idx,
                    end=tok.idx + len(tok.text),
                    is_word=is_word,
                    lemma=lemma if is_word else "",
                    pos=pos,
                    learnable=is_word and pos in LEARNABLE_POS,
                    lookup_forms=forms,
                )
            )
        sentences = [Sentence(s.start_char, s.end_char) for s in doc.sents]
        return tokens, sentences
