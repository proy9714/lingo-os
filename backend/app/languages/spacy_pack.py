"""Word splitters built on spaCy models that are downloaded when a language is added (data/models/<name>).

SpacyPack   French, Italian, Portuguese, Romanian, Russian: lemmas and parts of speech from the model, pronouns attached
            with a hyphen or apostrophe looked up through the word they hang on (Portuguese "fizeram-no" → fazer).
KoreanPack  spaCy's Korean model writes lemmas as morphemes ("먹+었+습니다"): a verb or adjective becomes its
            dictionary form (먹다), a noun loses its particle (밥을 → 밥).
ChinesePack Chinese has no inflection: the word is its own lemma, and the reading is its pinyin.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.languages.base import LEARNABLE_POS, Sentence, Token

# Models live in <data>/models; set at startup (main.bootstrap), else found from the config.
MODELS_DIR: list[Path] = []


class ModelMissing(RuntimeError):
    """The language was added but its model hasn't finished downloading."""


def load_model(name: str):
    import importlib.util

    import spacy

    if importlib.util.find_spec(name) is not None:
        return spacy.load(name, exclude=["ner"])
    if not MODELS_DIR:
        from app.config import load_config

        MODELS_DIR.append(load_config().data_dir / "models")
    path = MODELS_DIR[0] / name
    if not (path / "config.cfg").exists():
        raise ModelMissing(f"the language model {name} isn't downloaded yet")
    return spacy.load(path, exclude=["ner"])


# Pronouns written onto the verb with a hyphen (Portuguese, some French) or an apostrophe (Italian gliel', French l').
# Romanian ș and ț are often typed with a cedilla (ş, ţ, from old keyboards); the model and Wiktionary use the comma.
# One character for one, so token offsets still match the text.
COMMA_BELOW = str.maketrans("şţŞŢ", "șțȘȚ")
HYPHEN_CLITIC = re.compile(r"^(?P<word>[^\W\d_]{2,})-(?:[^\W\d_]{1,5})(?:-[^\W\d_]{1,5})?$")


class SpacyPack:
    def __init__(self, code: str, model: str) -> None:
        self.code = code
        self.nlp = load_model(model)

    def _lemma(self, tok) -> tuple[str, str]:  # noqa: ANN001 - spaCy token
        lemma, pos = tok.lemma_ or tok.text, tok.pos_
        if " " in lemma:
            lemma = lemma.split()[0]
        match = HYPHEN_CLITIC.match(tok.text)
        if match and lemma.lower() == tok.text.lower():
            word = self.nlp(match["word"])[0]
            lemma, pos = word.lemma_ or match["word"], word.pos_ if word.pos_ != "X" else "VERB"
        return lemma, pos

    def analyze(self, text: str) -> tuple[list[Token], list[Sentence]]:
        doc = self.nlp(text.translate(COMMA_BELOW) if self.code == "ro" else text)
        tokens: list[Token] = []
        for tok in doc:
            if tok.is_space:
                continue
            is_word = any(ch.isalpha() for ch in tok.text)
            lemma, pos = self._lemma(tok) if is_word else ("", tok.pos_)
            if is_word and pos != "PROPN":
                lemma = lemma.lower()
            surface = tok.text.lower().rstrip("'’")
            tokens.append(
                Token(
                    text=tok.text,
                    start=tok.idx,
                    end=tok.idx + len(tok.text),
                    is_word=is_word,
                    lemma=lemma,
                    pos=pos,
                    learnable=is_word and pos in LEARNABLE_POS,
                    lookup_forms=tuple(dict.fromkeys(f for f in (surface, tok.lemma_.lower()) if f)) if is_word else (),
                )
            )
        return tokens, [Sentence(s.start_char, s.end_char) for s in doc.sents]


HANGUL = re.compile(r"[가-힣]")
PREDICATES = {"VERB", "ADJ", "AUX"}


class KoreanPack:
    code = "ko"

    def __init__(self) -> None:
        self.nlp = load_model("ko_core_news_sm")

    def analyze(self, text: str) -> tuple[list[Token], list[Sentence]]:
        doc = self.nlp(text)
        tokens: list[Token] = []
        for tok in doc:
            if tok.is_space:
                continue
            is_word = bool(HANGUL.search(tok.text)) or any(ch.isalpha() for ch in tok.text)
            pos = tok.pos_
            parts = [p for p in (tok.lemma_ or tok.text).split("+") if p]
            stem = parts[0] if parts else tok.text
            if not is_word:
                lemma = ""
            elif pos in PREDICATES and len(parts) > 1 and HANGUL.search(stem):
                lemma = stem + "다"  # 먹+었+습니다 → 먹다
            else:
                lemma = stem  # 밥+을 → 밥
            tokens.append(
                Token(
                    text=tok.text,
                    start=tok.idx,
                    end=tok.idx + len(tok.text),
                    is_word=is_word,
                    lemma=lemma,
                    pos=pos,
                    learnable=is_word and pos in LEARNABLE_POS,
                    lookup_forms=tuple(dict.fromkeys((lemma, stem, tok.text))) if is_word else (),
                )
            )
        return tokens, [Sentence(s.start_char, s.end_char) for s in doc.sents]


HAN = re.compile(r"[㐀-鿿豈-﫿]")


def pinyin(word: str) -> str:
    from pypinyin import Style, pinyin as to_pinyin

    return " ".join(p[0] for p in to_pinyin(word, style=Style.TONE, heteronym=False))


class ChinesePack:
    code = "zh"

    def __init__(self) -> None:
        self.nlp = load_model("zh_core_web_sm")

    def analyze(self, text: str) -> tuple[list[Token], list[Sentence]]:
        doc = self.nlp(text)
        tokens: list[Token] = []
        for tok in doc:
            if tok.is_space:
                continue
            is_word = bool(HAN.search(tok.text)) or any(ch.isalpha() for ch in tok.text)
            han = bool(HAN.search(tok.text))
            tokens.append(
                Token(
                    text=tok.text,
                    start=tok.idx,
                    end=tok.idx + len(tok.text),
                    is_word=is_word,
                    lemma=tok.text if is_word else "",
                    reading=pinyin(tok.text) if han else "",
                    pos=tok.pos_,
                    learnable=is_word and tok.pos_ in LEARNABLE_POS,
                    lookup_forms=(tok.text,) if is_word else (),
                )
            )
        return tokens, [Sentence(s.start_char, s.end_char) for s in doc.sents]
