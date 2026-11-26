"""Comprehensible Input Value: series, exploring places, a lopsided level fit, weights learned from what you open."""

from __future__ import annotations

import time

from sqlalchemy import text

from app.services import calibration, discover, ranker, recommend
from test_ranker import _contains, _item, _lexeme, _session


def test_a_little_too_easy_costs_less_than_a_little_too_hard() -> None:
    lo, hi = 0.88, 0.97  # centre 0.925
    _, easier = calibration.band_and_fit(0.965, lo, hi)
    _, harder = calibration.band_and_fit(0.885, lo, hi)
    assert easier > harder
    assert calibration.band_and_fit(0.925, lo, hi)[1] == 1.0


def test_the_next_episode_of_a_series_you_follow_comes_first(client) -> None:
    with client.app.state.engine.begin() as conn:
        series = conn.execute(text("INSERT INTO collections (language_code, kind, title) VALUES ('de', 'podcast', 'Show')")).lastrowid
        episodes = [_item(conn, f"Folge {n}", creator="Show") for n in (1, 2, 3)]
        for n, item in enumerate(episodes, start=1):
            conn.execute(text("UPDATE content_items SET collection_id = :c, collection_index = :n WHERE id = :i"), {"c": series, "n": n, "i": item})
        _session(conn, episodes[0], 2)
        conn.execute(text("UPDATE content_items SET status = 'finished' WHERE id = :i"), {"i": episodes[0]})
        assert ranker.series_next(conn, "de", episodes) == {episodes[1]}
    pick = next(i for i in client.get("/api/feed", params={"lang": "de", "shelf": "watch"}).json()["items"] if i["id"] == episodes[1])
    assert "the next one in a series you're following" in pick["reasons"] and pick["explain"]["parts"]["series"] == 1.0


def test_some_places_go_to_something_new_to_try() -> None:
    known = [{"id": n, "type": "youtube", "creator": "Bekannt", "kind": "video", "estimated": False, "_score": 1.0 - n / 100} for n in range(10)]
    new = {"id": 99, "type": "youtube", "creator": "Neu", "kind": "video", "estimated": True, "_score": 0.3}
    ctx = {"learning": {}, "tried": {"bekannt"}}
    order = ranker.diversify(known + [new], lambda i: i["_score"], {}, ctx)
    assert order[ranker.EXPLORE_FIRST]["id"] == 99 and order[ranker.EXPLORE_FIRST]["_explore"]
    assert not any(i.get("_explore") for i in order if i["id"] != 99)


def test_the_list_doesnt_bring_back_the_same_words_twice_in_a_row() -> None:
    items = [
        {"id": 1, "type": "youtube", "creator": "A", "kind": "video", "estimated": False, "_score": 1.0},
        {"id": 2, "type": "youtube", "creator": "B", "kind": "video", "estimated": False, "_score": 0.95},
        {"id": 3, "type": "youtube", "creator": "C", "kind": "video", "estimated": False, "_score": 0.9},
    ]
    ctx = {"learning": {1: [10, 11, 12], 2: [10, 11, 12], 3: [20, 21]}, "tried": {"a", "b", "c"}}
    order = [i["id"] for i in ranker.diversify(items, lambda i: i["_score"], {}, ctx, explore=False)]
    assert order == [1, 3, 2]  # 2 would bring back the very words 1 already does


def test_weights_follow_what_you_open(monkeypatch) -> None:
    from app.db import settings_store

    stored: dict = {}
    monkeypatch.setattr(settings_store, "get", lambda conn, key, default=None: stored.get(key, default))
    monkeypatch.setattr(settings_store, "put", lambda conn, key, value: stored.__setitem__(key, value))
    rows = []
    for n in range(200):  # cards that teach more get opened far more often
        learn = (n % 10) / 10 - 0.5
        rows.append(({"learn": learn, "reinforce": 0.0}, learn > 0.1 or n % 7 == 0))
    fitted = ranker.fit_weights(None, "de", rows, force=True)
    assert fitted["fitted"] and fitted["weights"]["learn"] > ranker.WEIGHTS["learn"]
    assert fitted["weights"]["learn"] <= ranker.WEIGHTS["learn"] * ranker.WEIGHT_RANGE[1]
    few = ranker.fit_weights(None, "de", rows[:5], force=True)  # too little to go on: the hand-set weights
    assert not few["fitted"] and few["weights"] == ranker.WEIGHTS


def test_weights_are_learned_from_cards_shown_in_the_app(client) -> None:
    with client.app.state.engine.begin() as conn:
        for n in range(40):
            item = _item(conn, f"Karte {n}", creator=f"K{n % 5}", opened=n % 4 == 0)
            conn.execute(
                text("INSERT INTO item_impressions (content_item_id, shown, first_shown_at, last_shown_at) VALUES (:i, 3, '2026-11-01T00:00:00.000Z', '2026-11-01T00:00:00.000Z')"),
                {"i": item},
            )
        result = recommend.learn_weights(conn, "de", force=True)
    assert result["impressions"] == 40 and result["fitted"] and result["opened"] == 10


def test_good_measured_suggestions_are_kept_longer_than_others(client) -> None:
    with client.app.state.engine.begin() as conn:
        good = _item(conn, "passt", band="i_plus_1")
        off = _item(conn, "zu schwer", band="too_hard")
        conn.execute(text("UPDATE content_items SET added_at = '2020-01-01T00:00:00.000Z', analysis_status = 'done'"))
        conn.execute(text("UPDATE content_scores SET estimated = 0"))
        conn.execute(text("UPDATE content_items SET added_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-40 days')"))
        assert discover.prune(conn, 30, "de") == 1
        remaining = {r[0] for r in conn.execute(text("SELECT id FROM content_items")).all()}
    assert good in remaining and off not in remaining


def test_ranking_a_big_library_stays_quick(client) -> None:
    with client.app.state.engine.begin() as conn:
        words = [_lexeme(conn, f"w{n}", 500 + n * 7) for n in range(400)]
        for n in range(1500):
            item = _item(conn, f"Video {n}", creator=f"Kanal {n % 60}", fit=0.3 + (n % 50) / 100)
            for k in range(12):
                conn.execute(
                    text("INSERT INTO content_lemmas (content_item_id, lexeme_id, count) VALUES (:i, :x, :c)"),
                    {"i": item, "x": words[(n * 7 + k * 31) % len(words)], "c": 1 + k % 3},
                )
    with client.app.state.engine.begin() as conn:
        recommend.invalidate()
        started = time.perf_counter()
        ranked = recommend.ranked(conn, "de", "watch")
        elapsed = time.perf_counter() - started
    assert len(ranked) == 1500
    assert elapsed < 5.0, f"ranking 1,500 items took {elapsed:.2f}s"
