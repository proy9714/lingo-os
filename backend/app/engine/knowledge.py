"""One rule for "how likely do you know this word", shared by colouring and content scoring."""

from __future__ import annotations

import math

from app.engine.vocab_model import p_known

# Each time a word is heard in content you watched, a little of the remaining doubt goes away:
# after ~12 hearings about two thirds of it is gone.
EXPOSURE_SCALE = 12.0


def knowledge_p(
    rank: int | None,
    status: str | None,
    p_user: float | None,
    heard: int,
    r50: float,
    k: float,
) -> float:
    if status == "ignored":
        return 1.0
    if status and status != "seen" and p_user is not None:
        return p_user  # your explicit status wins
    base = p_user if p_user is not None else p_known(rank, r50, k)
    return 1.0 - (1.0 - base) * math.exp(-heard / EXPOSURE_SCALE) if heard else base
