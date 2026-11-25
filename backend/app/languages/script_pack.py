"""Hindi, Bengali and Arabic: words split by spaCy's own rules for the language (no model to download), dictionary
forms found through Wiktionary's "form of" entries (see `languages._repair`).

Arabic writes short vowels (harakat) only sometimes, and glues the article and short words to the next word
(والناس = و + ال + ناس, "and the people"), so a word is looked up as written, without vowel marks, and without those
prefixes; the first form the dictionary knows becomes the word's identity.
"""

from __future__ import annotations

import re
from functools import cached_property

from app.languages.base import Sentence, Token

# Arabic vowel marks, shadda, sukun, dagger alif, Quranic marks, and the tatweel stretch
ARABIC_MARKS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")
# Arabic letters glued to the front of a word, longest first: and/so + by/for/like + the
ARABIC_PREFIXES = ("وبال", "وكال", "وال", "فال", "بال", "كال", "لل", "ال", "و", "ف", "ب", "ل", "ك")
SINGLE = frozenset({"و", "ف", "ب", "ل", "ك"})  # one letter: only trusted when what's left is itself a dictionary word
# attached pronouns (her, their, our, my…), longest first
ARABIC_SUFFIXES = ("هما", "كما", "ها", "هم", "هن", "كم", "كن", "نا", "ني", "ه", "ك", "ي")
# Hindi/Bengali: nukta spellings are interchangeable in practice (ज़ / ज़), so both are tried
_NUKTA = "़"


def strip_marks(code: str, text: str) -> str:
    """The form a dictionary lists: Arabic without vowel marks; other languages unchanged."""
    return ARABIC_MARKS.sub("", text) if code == "ar" else text


def _arabic_split(word: str) -> tuple[list[str], set[str]]:
    """All candidate spellings of an Arabic word, and the ones that rest on a guess (a stripped one-letter prefix)."""
    bare = strip_marks("ar", word)
    forms, weak = [bare], set()
    stems: list[tuple[str, bool]] = [(bare, False)]
    for prefix in ARABIC_PREFIXES:
        if bare.startswith(prefix) and len(bare) - len(prefix) >= 2:
            rest, guess = bare[len(prefix):], prefix in SINGLE
            stems.append((rest, guess))
            if prefix not in {"ال", "وال", "فال", "بال", "كال", "لل", "وبال", "وكال"} and rest.startswith("ال") and len(rest) > 3:
                stems.append((rest[2:], guess))  # و + الناس → الناس → ناس
    for stem, guess in list(stems):
        for suffix in ARABIC_SUFFIXES:  # أصدقائها → أصدقاء, مدرستي → مدرسة
            if stem.endswith(suffix) and len(stem) - len(suffix) >= 2:
                base, weak_end = stem[: -len(suffix)], guess or len(suffix) == 1
                stems.append((base, weak_end))
                if base.endswith("ت"):  # مدرستي → مدرسة
                    stems.append((base[:-1] + "ة", weak_end))
                if base.endswith(("ئ", "ؤ")):  # the hamza changes seat before an ending: أصدقائها → أصدقاء
                    stems.append((base[:-1] + "ء", weak_end))
                break
    for stem, guess in stems[1:]:
        forms.append(stem)
        if guess:
            weak.add(stem)
    # hamza seats a dictionary may write differently
    for stem in list(forms):
        plain = stem.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
        if plain != stem:
            forms.append(plain)
            if stem in weak:
                weak.add(plain)
    ordered = list(dict.fromkeys(forms))
    return ordered, {f for f in weak if f not in set(ordered[:1])}


def arabic_forms(word: str) -> tuple[str, ...]:
    """'والناسُ' → ('والناس', 'الناس', 'ناس', …): as written, then without glued prefixes and pronoun endings."""
    return tuple(_arabic_split(word)[0])


def guessed_forms(code: str, word: str) -> frozenset[str]:
    """Spellings that only count if the dictionary lists them as words (not through 'form of')."""
    return frozenset(_arabic_split(word)[1]) if code == "ar" else frozenset()


class ScriptPack:
    """A language pack built on spaCy's blank pipeline: tokenizer, sentence splitter and stop-word list."""

    def __init__(self, code: str) -> None:
        self.code = code

    @cached_property
    def nlp(self):  # noqa: ANN201 - spaCy Language
        import spacy

        nlp = spacy.blank(self.code)
        nlp.add_pipe("sentencizer")
        return nlp

    @cached_property
    def stop_words(self) -> frozenset[str]:
        return frozenset(strip_marks(self.code, w) for w in self.nlp.Defaults.stop_words)

    def analyze(self, text: str) -> tuple[list[Token], list[Sentence]]:
        doc = self.nlp(text)
        tokens: list[Token] = []
        for t in doc:
            if t.is_space:
                continue
            letters = any(ch.isalpha() for ch in t.text)
            is_word = letters and not t.like_num and not t.is_punct
            if not is_word:
                tokens.append(Token(t.text, t.idx, t.idx + len(t.text), False))
                continue
            if self.code == "ar":
                forms = arabic_forms(t.text)
            else:
                forms = tuple(dict.fromkeys([t.text, t.text.replace(_NUKTA, "")]))
            lemma = forms[0]
            stop = lemma in self.stop_words or any(f in self.stop_words for f in forms[1:2])
            tokens.append(
                Token(
                    t.text, t.idx, t.idx + len(t.text), True, lemma=lemma, pos="X",
                    learnable=not stop and len(lemma) > 1, lookup_forms=forms,
                )
            )
        sentences = [Sentence(s.start_char, s.end_char) for s in doc.sents]
        return tokens, sentences
