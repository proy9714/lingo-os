"""Frequency-based vocabulary model (ARCHITECTURE §6.3).

P(known | rank r) = 1 / (1 + (r / r50)^k)

r50 is the rank where you know half the words (your "frontier"); k is how sharp the
drop-off is. Expected vocabulary = Σ P(known) over the ranked list.
"""

from __future__ import annotations

import math
from functools import lru_cache

import numpy as np

DEFAULT_K = 2.5
MAX_RANK = 50_000
UNRANKED = 100_000  # rank assumed for words not in the frequency list

_RANKS = np.arange(1, MAX_RANK + 1, dtype=np.float64)


def p_known(rank: int | None, r50: float, k: float = DEFAULT_K) -> float:
    r = UNRANKED if rank is None else max(1, rank)
    return 1.0 / (1.0 + (r / r50) ** k)


@lru_cache(maxsize=4096)
def expected_vocabulary(r50: float, k: float = DEFAULT_K) -> float:
    return float(np.sum(1.0 / (1.0 + (_RANKS / r50) ** k)))


def solve_r50(words: float, k: float = DEFAULT_K) -> float:
    """The r50 whose expected vocabulary equals `words` (bisection in log space)."""
    words = max(10.0, min(words, MAX_RANK * 0.9))
    lo, hi = math.log(1.0), math.log(MAX_RANK * 4)
    for _ in range(60):
        mid = (lo + hi) / 2
        if expected_vocabulary(round(math.exp(mid), 3), k) < words:
            lo = mid
        else:
            hi = mid
    return round(math.exp((lo + hi) / 2), 1)
