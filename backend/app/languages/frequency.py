"""Word frequency ranks from wordfreq (lists are lowercase; rank 1 = most frequent)."""

from __future__ import annotations

from functools import lru_cache

from wordfreq import top_n_list

LIST_SIZE = 50_000


@lru_cache(maxsize=None)
def top_words(lang: str) -> tuple[str, ...]:
    return tuple(top_n_list(lang, LIST_SIZE))


@lru_cache(maxsize=None)
def _ranks(lang: str) -> dict[str, int]:
    return {word: index + 1 for index, word in enumerate(top_words(lang))}


def rank_of(lang: str, *forms: str) -> int | None:
    """Best (lowest) rank among the given forms, or None if none is in the top list."""
    ranks = _ranks(lang)
    found = [ranks[f.lower()] for f in forms if f and f.lower() in ranks]
    return min(found) if found else None


def word_at(lang: str, rank: int) -> str:
    words = top_words(lang)
    return words[max(1, min(rank, len(words))) - 1]
