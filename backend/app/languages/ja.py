"""Japanese: fugashi + UniDic (lite).

A verb or adjective is grouped with the auxiliaries that follow it, so 間に合わない or
食べている is one clickable word whose lemma is the dictionary form (間に合う, 食べる).
"""

from __future__ import annotations

import re

import fugashi

from app.languages.base import Sentence, Token

SENTENCE_END = re.compile(r"[。！？!?\n]+")
JAPANESE_CHAR = re.compile(r"[぀-ヿ㐀-鿿豈-﫿々〆ー]")

POS_MAP = {
    "名詞": "NOUN",
    "動詞": "VERB",
    "形容詞": "ADJ",
    "形状詞": "ADJ",  # na-adjectives
    "副詞": "ADV",
    "感動詞": "INTJ",
    "連体詞": "DET",
    "接続詞": "CCONJ",
    "代名詞": "PRON",
    "助詞": "ADP",
    "助動詞": "AUX",
    "接尾辞": "PART",
    "接頭辞": "PART",
    "補助記号": "PUNCT",
    "記号": "SYM",
    "空白": "SPACE",
}
GROUP_HEADS = {"動詞", "形容詞", "形状詞"}


def to_hiragana(katakana: str) -> str:
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in katakana)


def _clean_lemma(lemma: str) -> str:
    # UniDic writes loanwords as 'テレビ-television'; keep the Japanese part.
    return lemma.split("-", 1)[0] if lemma else lemma


class JapanesePack:
    code = "ja"

    def __init__(self) -> None:
        self.tagger = fugashi.Tagger()

    def analyze(self, text: str) -> tuple[list[Token], list[Sentence]]:
        words = []
        cursor = 0
        for word in self.tagger(text):
            start = text.find(word.surface, cursor)
            if start < 0:  # should not happen; keep offsets monotonic
                start = cursor
            end = start + len(word.surface)
            cursor = end
            words.append((word, start, end))

        tokens: list[Token] = []
        i = 0
        while i < len(words):
            word, start, end = words[i]
            feature = word.feature
            pos1 = feature.pos1 or ""
            j = i + 1
            if pos1 in GROUP_HEADS:
                while j < len(words):
                    nxt = words[j][0].feature
                    if nxt.pos1 == "助動詞":
                        j += 1
                    elif nxt.pos1 == "助詞" and nxt.pos2 == "接続助詞" and words[j][0].surface in {"て", "で"}:
                        # て/で only joins when an auxiliary verb (いる, しまう, …) follows
                        if j + 1 < len(words) and words[j + 1][0].feature.pos2 == "非自立可能":
                            j += 2
                        else:
                            break
                    elif nxt.pos1 == "動詞" and nxt.pos2 == "非自立可能":
                        j += 1
                    else:
                        break
            elif pos1 == "名詞":
                while j < len(words) and words[j][0].feature.pos1 == "接尾辞":
                    j += 1
            group_end = words[j - 1][2]
            surface = text[start:group_end]
            is_word = bool(JAPANESE_CHAR.search(surface)) or any(ch.isalpha() for ch in surface)
            pos = POS_MAP.get(pos1, "X")
            if pos1 == "名詞" and feature.pos2 in {"固有名詞"}:
                pos = "PROPN"
            if pos1 == "名詞" and feature.pos2 == "数詞":
                pos = "NUM"
            base = feature.orthBase or word.surface
            lemma = _clean_lemma(feature.lemma or base)
            reading = to_hiragana(feature.lForm or feature.kana or "") if is_word else ""
            learnable = is_word and pos in {"NOUN", "VERB", "ADJ", "ADV", "INTJ"}
            tokens.append(
                Token(
                    text=surface,
                    start=start,
                    end=group_end,
                    is_word=is_word,
                    lemma=lemma if is_word else "",
                    reading=reading,
                    pos=pos,
                    learnable=learnable,
                    lookup_forms=tuple(dict.fromkeys(f for f in (base, lemma, surface) if f)) if is_word else (),
                    base=base if is_word else "",
                )
            )
            i = j

        sentences = []
        start = 0
        for match in SENTENCE_END.finditer(text):
            if match.end() > start and text[start : match.start()].strip():
                sentences.append(Sentence(start, match.end()))
            start = match.end()
        if text[start:].strip():
            sentences.append(Sentence(start, len(text)))
        return tokens, sentences
