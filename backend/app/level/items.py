"""Test items drawn from the frequency list and checked against your dictionaries, plus pseudo-words."""

from __future__ import annotations

import random
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import lru_cache

from sqlalchemy import Connection
from wordfreq import zipf_frequency

from app.dictionary.lookup import display_gloss, lookup
from app.languages.frequency import LIST_SIZE, rank_of, top_words, word_at
from app.languages.registry import get as language_spec

KANJI = re.compile(r"[㐀-鿿]")
JAPANESE = re.compile(r"[぀-ヿ㐀-鿿]")
HAN_WORD = re.compile(r"^[㐀-鿿]+$")
HANGUL_WORD = re.compile(r"^[가-힣]+$")


def _script(lang: str) -> str:
    spec = language_spec(lang)
    return spec.script if spec else "latin"

ACCEPT = {"n", "v", "adj", "adv"}
REJECT = {
    "name", "pron", "prep", "conj", "art", "det", "num", "particle", "intj", "phrase", "prefix", "suffix",
    "abbrev", "abbr", "contraction", "character", "symbol", "postp", "proverb", "punct", "affix",
}
JA_ACCEPT = ("noun", "dan", "verb", "adjective", "adverb")
JA_REJECT = ("particle", "auxiliary", "conjunction", "pronoun", "counter", "prefix")


@dataclass(frozen=True)
class Candidate:
    rank: int
    word: str  # as shown, e.g. 'Miete' (the dictionary's spelling)
    reading: str
    gloss: str


_ELIGIBLE: dict[tuple[str, str], Candidate | None] = {}


def _acceptable(lang: str, pos: list[str]) -> bool:
    tags = [p.lower() for p in pos]
    if lang == "ja":
        if any(bad in t for t in tags for bad in JA_REJECT):
            return False
        return any(good in t for t in tags for good in JA_ACCEPT)
    if any(t in REJECT for t in tags):
        return False
    return any(t in ACCEPT for t in tags)


def eligible(dict_conn: Connection, lang: str, rank: int) -> Candidate | None:
    word = word_at(lang, rank)
    key = (lang, word)
    if key in _ELIGIBLE:
        cached = _ELIGIBLE[key]
        return Candidate(rank, cached.word, cached.reading, cached.gloss) if cached else None
    result: Candidate | None = None
    script = _script(lang)
    if lang == "ja":
        ok = bool(JAPANESE.search(word)) and (len(word) >= 2 or bool(KANJI.search(word)))
    elif script == "han":
        ok = bool(HAN_WORD.match(word))
    elif script == "hangul":
        ok = bool(HANGUL_WORD.match(word))
    else:
        ok = len(word) >= 3 and word.isalpha()
    if ok:
        for entry in lookup(dict_conn, lang, [word], limit=4)["entries"]:
            if entry["via_inflection"] or entry["term"].lower() != word.lower():
                continue
            if not _acceptable(lang, entry["pos"]):
                continue
            gloss = display_gloss(entry["glosses"][0], 70)
            if len(gloss) >= 2:
                result = Candidate(rank, entry["term"], entry["reading"], gloss)
                break
    _ELIGIBLE[key] = result
    return result


def candidate_near(dict_conn: Connection, lang: str, target: int, used: set[str], max_scan: int = 400) -> Candidate | None:
    target = max(1, min(int(target), LIST_SIZE))
    for offset in range(max_scan):
        for rank in ((target,) if offset == 0 else (target + offset, target - offset)):
            if not 1 <= rank <= LIST_SIZE:
                continue
            found = eligible(dict_conn, lang, rank)
            if found and found.word.lower() not in used:
                return found
    return None


def distractors(
    dict_conn: Connection, lang: str, rank: int, correct: str, used: set[str], rng: random.Random, n: int = 3
) -> list[str]:
    out: list[str] = []
    taken = set(used)
    for _ in range(40):
        if len(out) >= n:
            break
        candidate = candidate_near(dict_conn, lang, int(rank * rng.uniform(0.5, 2.0)), taken, max_scan=60)
        if not candidate:
            continue
        taken.add(candidate.word.lower())
        gloss = candidate.gloss
        if gloss.lower()[:18] == correct.lower()[:18] or any(gloss.lower()[:18] == o.lower()[:18] for o in out):
            continue
        out.append(gloss)
    return out


# ------------------------------------------------------------------ pseudo-words


@lru_cache(maxsize=None)
def _trigrams(lang: str) -> dict[str, Counter]:
    model: dict[str, Counter] = defaultdict(Counter)
    shortest = 2 if _script(lang) == "hangul" else 4  # Korean counts syllables, not letters
    for word in top_words(lang)[:20_000]:
        if not word.isalpha() or len(word) < shortest:
            continue
        padded = f"^^{word}$"
        for i in range(len(padded) - 2):
            model[padded[i : i + 2]][padded[i + 2]] += 1
    return dict(model)


@lru_cache(maxsize=None)
def _kanji_pool(lang: str = "ja") -> tuple[str, ...]:
    """Common characters (kanji, hanzi) for two-character non-words."""
    pool: list[str] = []
    for word in top_words(lang)[:4000]:
        pool.extend(KANJI.findall(word))
    return tuple(dict.fromkeys(pool))


def _is_real(dict_conn: Connection, lang: str, word: str) -> bool:
    if rank_of(lang, word) is not None:
        return True
    if _script(lang) in {"latin", "cyrillic"} and zipf_frequency(word, lang) > 0:  # CJK needs a tokenizer here
        return True
    found = lookup(dict_conn, lang, [word], limit=1)
    return bool(found["entries"] or found["inflections"])


def pseudo_word(dict_conn: Connection, lang: str, rng: random.Random) -> str | None:
    """A plausible-looking non-word: saying you know it reveals over-claiming."""
    if _script(lang) in {"japanese", "han"}:
        pool = _kanji_pool(lang)
        for _ in range(300):
            word = rng.choice(pool) + rng.choice(pool)
            if word[0] != word[1] and not _is_real(dict_conn, lang, word):
                return word
        return None
    model = _trigrams(lang)
    for _ in range(400):
        state, word = "^^", ""
        while len(word) < 14:
            options = model.get(state)
            if not options:
                break
            letters, weights = zip(*options.items())
            nxt = rng.choices(letters, weights)[0]
            if nxt == "$":
                break
            word += nxt
            state = state[1] + nxt
        low, high = (2, 4) if _script(lang) == "hangul" else (6, 11)
        if low <= len(word) <= high and not _is_real(dict_conn, lang, word):
            return word.capitalize() if lang == "de" and rng.random() < 0.5 else word
    return None
