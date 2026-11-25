"""The rebuilt recommender: what an item teaches, words due again, speech speed, skips, exploration and variety."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import text

from app.services import ranker, recommend, taste
from app.timeutil import to_iso, utc_now


def _item(conn, title: str, *, creator: str = "Kanal", kind: str = "youtube", band: str = "i_plus_1", fit: float = 0.8,
          duration: int = 600, words: int | None = None, status: str = "candidate", opened: bool = False) -> int:
    item_id = conn.execute(
        text(
            "INSERT INTO content_items (language_code, type, title, creator, origin, source, external_id, status, progress, "
            "analysis_status, duration_sec, word_count, last_opened_at) VALUES ('de', :k, :t, :c, 'scraper', 'x', :t, :s, 0, "
            "'done', :d, :w, :o)"
        ),
        {"k": kind, "t": title, "c": creator, "s": status, "d": duration, "w": words, "o": to_iso(utc_now()) if opened else None},
    ).lastrowid
    conn.execute(
        text("INSERT INTO content_scores (content_item_id, profile_version, coverage, expected_unknown, i1_score, band) "
             "VALUES (:i, 1, 0.94, 12, :f, :b)"),
        {"i": item_id, "f": fit, "b": band},
    )
    return item_id


def _lexeme(conn, lemma: str, rank: int | None, status: str | None = None, changed_days_ago: float = 0) -> int:
    lex = conn.execute(
        text("INSERT INTO lexemes (language_code, lemma, freq_rank) VALUES ('de', :l, :r)"), {"l": lemma, "r": rank}
    ).lastrowid
    if status:
        when = to_iso(utc_now() - timedelta(days=changed_days_ago))
        conn.execute(
            text("INSERT INTO user_words (lexeme_id, status, p_known, status_changed_at, first_seen_at) VALUES (:x, :s, 0.3, :w, :w)"),
            {"x": lex, "s": status, "w": when},
        )
    return lex


def _contains(conn, item_id: int, *lexemes: int) -> None:
    for lex in lexemes:
        conn.execute(text("INSERT INTO content_lemmas (content_item_id, lexeme_id, count) VALUES (:i, :x, 2)"), {"i": item_id, "x": lex})


def _session(conn, item_id: int, days_ago: float, seconds: int = 600) -> None:
    conn.execute(
        text(
            "INSERT INTO activity_sessions (language_code, activity, modality, tracking, content_item_id, started_at, active_seconds) "
            "VALUES ('de', 'video', 'listening', 'auto', :i, :t, :s)"
        ),
        {"i": item_id, "t": to_iso(utc_now() - timedelta(days=days_ago)), "s": seconds},
    )


def test_learning_words_come_back_on_a_widening_schedule(client) -> None:
    with client.app.state.engine.begin() as conn:
        fresh = _lexeme(conn, "anrufen", 900, "learning", changed_days_ago=0.1)
        old = _lexeme(conn, "erledigen", 2100, "learning", changed_days_ago=30)
        met = _lexeme(conn, "Zeitpunkt", 2500, "learning", changed_days_ago=30)
        watched = _item(conn, "watched", status="finished")
        _contains(conn, watched, met)
        for days in (20, 12, 9):  # met on three days: next meeting due after 8 days
            _session(conn, watched, days)
        due = ranker.due_words(conn, "de")
    assert due[old] == 1.0 and due[fresh] < 0.2
    assert 0.9 < due[met] <= 1.0  # last met 9 days ago, interval 8 days

    with client.app.state.engine.begin() as conn:
        _session(conn, watched, 1)  # met again yesterday: not due for a while
        assert ranker.due_words(conn, "de")[met] < 0.2


def test_common_new_words_teach_more_than_rare_ones(client) -> None:
    with client.app.state.engine.begin() as conn:
        common = _item(conn, "common words")
        rare = _item(conn, "rare words")
        _contains(conn, common, *[_lexeme(conn, f"häufig{n}", 2000 + n) for n in range(6)])
        _contains(conn, rare, *[_lexeme(conn, f"selten{n}", 30000 + n) for n in range(6)])
        shares = ranker.teach_shares(conn, [common, rare])
        items = recommend.candidates(conn, "de", "watch")
        ctx = ranker.context(conn, "de", items)
    assert shares[common] == (1.0, 6) and shares[rare] == (0.0, 6)
    by_id = {i["id"]: i for i in items}
    assert ranker.boost(by_id[common], ctx) > 1.2 > 0.85 > ranker.boost(by_id[rare], ctx)


def test_fast_speech_counts_against_a_video(client) -> None:
    item = {"id": 1, "estimated": False, "status": "candidate", "speech_wpm": 210.0}
    ctx = {"teach": {}, "due": {}, "learning": {}, "shown": {}, "comfort": 120.0}
    assert ranker.parts(item, ctx)["speed"] == -0.5
    assert ranker.parts({**item, "speech_wpm": 130.0}, ctx)["speed"] == 0.0
    assert ranker.parts({**item, "speech_wpm": 300.0}, {**ctx, "comfort": None})["speed"] == 0.0  # no evidence yet


def test_cards_passed_by_sink_but_count_once_per_six_hours(client) -> None:
    with client.app.state.engine.begin() as conn:
        passed = _item(conn, "passed by")
        opened = _item(conn, "opened", opened=True)
        assert ranker.record_seen(conn, [passed, passed, opened]) == 2
        assert ranker.record_seen(conn, [passed]) == 0  # again within 6 hours: not counted
        conn.execute(text("UPDATE item_impressions SET shown = 5"))
    item = {"id": passed, "estimated": False, "status": "candidate"}
    ctx = {"teach": {}, "due": {}, "learning": {}, "comfort": None, "shown": {passed: 5}}
    assert round(ranker.parts(item, ctx)["skipped"], 3) == -0.6
    assert ranker.parts({**item, "status": "in_progress"}, ctx)["skipped"] == 0.0
    with client.app.state.engine.connect() as conn:
        skipped = ranker.skipped_owners(conn, "de")
    assert [round(v, 3) for v in skipped.values()] == [0.45]  # only the card never opened counts against its channel
    assert client.post("/api/recommend/seen", json={"ids": [passed, 999999]}).json() == {"counted": 0}


def test_channels_are_explored_by_sampling_beliefs(client) -> None:
    profile = taste.TasteProfile("de", signals=10, day="2026-11-25")
    profile.channel_beliefs = {"liebling": (40.0, 2.0), "langweilig": (2.0, 40.0)}
    profile.channels = {"liebling": 0.9, "langweilig": -0.9}
    assert profile.sampled_channel("Liebling") > 0.7
    assert profile.sampled_channel("Langweilig") < -0.7
    assert profile.sampled_channel("Liebling") == profile.sampled_channel("Liebling")  # stable within a day
    unknown = [taste.TasteProfile("de", signals=10, day=f"2026-11-{d:02d}").sampled_channel("Neu") for d in range(1, 29)]
    assert min(unknown) < -0.2 and max(unknown) > 0.2  # an untried channel gets high draws on some days


def test_variety_mixes_channels_topics_and_lengths() -> None:
    items = [
        {"id": n, "type": "youtube", "creator": "Eins" if n < 6 else "Zwei", "duration_sec": 600, "word_count": None, "kind": "video",
         "_score": 1.0 - n * 0.01}
        for n in range(10)
    ]
    order = [i["creator"] for i in ranker.diversify(items, lambda i: i["_score"], {})]
    assert order[:4] in (["Eins", "Zwei", "Eins", "Zwei"], ["Eins", "Zwei", "Eins", "Eins"])
    assert "Zwei" in order[:2]


def test_today_prefers_what_fits_the_time_left() -> None:
    short, long = {"duration_sec": 8 * 60}, {"duration_sec": 45 * 60}
    assert ranker.time_fit(short, 10) == 1.15 and ranker.time_fit(long, 10) == 0.8
    assert ranker.time_fit(long, None) == 1.0 and ranker.time_fit({"word_count": 600}, 10) == 1.15


def test_up_next_and_feed_explain_the_new_reasons(client) -> None:
    with client.app.state.engine.begin() as conn:
        learning = [_lexeme(conn, f"lerne{n}", 3000 + n, "learning", changed_days_ago=10) for n in range(3)]
        item = _item(conn, "due words video")
        _contains(conn, item, *learning, *[_lexeme(conn, f"neu{n}", 2500 + n) for n in range(4)])
        _item(conn, "plain video", creator="Andere")
    feed = client.get("/api/feed", params={"lang": "de", "shelf": "watch"}).json()
    pick = next(i for i in feed["items"] if i["id"] == item)
    assert "brings back 3 words you're learning, due again" in pick["reasons"]
    assert "its new words are common, useful ones" in pick["reasons"]
    assert feed["items"][0]["id"] == item
    picks = client.get("/api/recommend", params={"lang": "de"}).json()["picks"]
    assert picks[0]["id"] == item
