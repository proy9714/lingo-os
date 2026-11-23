from __future__ import annotations

import math

import numpy as np

from app.engine.vocab_model import expected_vocabulary, p_known, solve_r50
from app.level.vocab_test import GRID, posterior


def test_p_known_falls_with_rank() -> None:
    assert p_known(10, 1000) > 0.99
    assert abs(p_known(1000, 1000) - 0.5) < 1e-9
    assert p_known(20_000, 1000) < 0.01
    assert p_known(None, 1000) < p_known(40_000, 1000)


def test_solve_r50_inverts_expected_vocabulary() -> None:
    for words in (500, 2_000, 8_000):
        r50 = solve_r50(words)
        assert abs(expected_vocabulary(r50) - words) / words < 0.01


def _simulate(frontier: float, n: int = 40, seed: int = 3) -> list[dict]:
    rng = np.random.default_rng(seed)
    items = []
    # Like the real test: words are drawn around the learner's frontier.
    ranks = np.clip(np.exp(rng.uniform(math.log(frontier / 4), math.log(frontier * 4), n)), 20, 30_000)
    for i, rank in enumerate(ranks):
        knows = rng.random() < p_known(int(rank), frontier)
        category = ("yes_right" if rng.random() < 0.92 else "yes_wrong") if knows else "no"
        items.append({"seq": i, "pseudo": False, "prompt": {"rank": int(rank)}, "response": {"category": category}})
    for j in range(6):  # an honest learner rejects pseudo-words
        items.append({"seq": 100 + j, "pseudo": True, "prompt": {}, "response": {"category": "no"}})
    return items


def test_posterior_recovers_a_simulated_frontier() -> None:
    for frontier in (600, 2_500, 9_000):
        w, fa = posterior(_simulate(frontier), prior_mu=math.log(1_000), k=2.5)
        estimate = math.exp(float(np.sum(w * GRID)))
        assert 0.6 < estimate / frontier < 1.6, (frontier, estimate)
        assert fa < 0.1


def test_overclaiming_on_pseudo_words_raises_false_alarm_rate() -> None:
    items = _simulate(2_000)
    for item in items:
        if item["pseudo"]:
            item["response"]["category"] = "yes_wrong"
    _, fa = posterior(items, prior_mu=math.log(1_000), k=2.5)
    assert fa > 0.4
