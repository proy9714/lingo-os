"""The adaptive memory model behind automatic word moves (engine/memory.py)."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import text

from app.engine import memory
from app.services import vocab, word_progress
from app.sync.hlc import HybridClock
from app.timeutil import to_iso, utc_now
from test_word_progress import _ago, _met, _status, _word


def _auto(conn, lexeme: int, status: str, days_ago: float) -> None:
    """Pretend an automatic move set this status `days_ago` days ago."""
    conn.execute(text("UPDATE user_words SET status = :s, status_changed_at = :t WHERE lexeme_id = :w"), {"s": status, "t": _ago(days_ago), "w": lexeme})
    conn.execute(
        text("INSERT INTO word_events (lexeme_id, event, value, created_at) VALUES (:w, 'status_change', :v, :t)"),
        {"w": lexeme, "v": f"{status} (automatic: met on 3 days)", "t": _ago(days_ago)},
    )


def _lookup(conn, lexeme: int, days_ago: float) -> None:
    conn.execute(text("INSERT INTO word_events (lexeme_id, event, created_at) VALUES (:w, 'lookup', :t)"), {"w": lexeme, "t": _ago(days_ago)})


def test_meeting_a_word_on_spaced_days_beats_meeting_it_often_on_one_day(client) -> None:
    with client.app.state.engine.begin() as conn:
        spaced = _word(conn, "Brücke", "learning", 20)
        _met(conn, spaced, [12, 7, 2], times=2)
        massed = _word(conn, "Mauer", "learning", 20)
        _met(conn, massed, [2, 2.01, 2.02], times=2)  # three sessions the same day
        state = memory.word_state(conn, "de", [spaced, massed])
    assert state[spaced].stability > 2 * state[massed].stability
    assert len(set(state[massed].evidence_days)) == 1


def test_only_the_share_you_watched_counts(client) -> None:
    with client.app.state.engine.begin() as conn:
        word = _word(conn, "Wolke", "learning", 20)
        _met(conn, word, [10, 6, 3])
        conn.execute(text("UPDATE content_items SET duration_sec = 6000"))  # 600 s of a 100-minute video: a tenth
        assert word_progress.promote(conn, "de") == []


def test_looking_a_word_up_again_moves_an_automatic_step_back(client) -> None:
    with client.app.state.engine.begin() as conn:
        word = _word(conn, "Spiegel", "learning", 30)
        _auto(conn, word, "known", 20)
        _lookup(conn, word, 10)
        assert word_progress.promote(conn, "de") == []  # one lookup: still known
        _lookup(conn, word, 5)
        moves = word_progress.promote(conn, "de")
        assert [(m["from"], m["to"], m["direction"]) for m in moves] == [("known", "familiar", "down")]
        assert _status(conn, word) == "familiar"
    recent = client.get("/api/vocab/moves", params={"lang": "de"}).json()["moves"]
    assert recent[0]["direction"] == "down"


def test_a_status_you_set_yourself_is_not_moved_back_against_you(client) -> None:
    with client.app.state.engine.begin() as conn:
        word = _word(conn, "Gabel", "known", 10)  # set by you
        for days in (8, 6, 4, 2):
            _lookup(conn, word, days)
        assert word_progress.promote(conn, "de") == []
        assert _status(conn, word) == "known"


def test_pace_and_turning_automatic_moves_off(client) -> None:
    with client.app.state.engine.begin() as conn:
        word = _word(conn, "Löffel", "learning", 20)
        _met(conn, word, [10, 6, 3])
        memory.set_preferences(conn, auto=False)
        assert word_progress.promote(conn, "de") == []
        memory.set_preferences(conn, auto=True, pace="cautious")  # needs more than three meetings now
        assert word_progress.promote(conn, "de") == []
        memory.set_preferences(conn, pace="balanced")
        assert [m["to"] for m in word_progress.promote(conn, "de")] == ["familiar"]
    assert client.put("/api/vocab/model", json={"pace": "eager"}).json()["preferences"] == {"auto": True, "pace": "eager"}
    assert client.put("/api/vocab/model", json={"pace": "fast"}).status_code == 422


def test_the_model_learns_a_learner_who_forgets_quickly(client) -> None:
    """Someone who keeps looking words up a few days after meeting them: growth is fitted lower than the default."""
    with client.app.state.engine.begin() as conn:
        for n in range(14):
            word = _word(conn, f"Wort{n}", "learning", 40)
            _met(conn, word, [30, 26, 22], times=3)
            _lookup(conn, word, 18 - n % 3)  # forgotten soon after
        fitted = memory.fit(conn, "de", force=True)
    assert fitted["labels"] >= 10
    assert fitted["g"] < memory.DEFAULTS["g"] or fitted["lapse"] < memory.DEFAULTS["lapse"]
    assert fitted["loss_fitted"] <= fitted["loss_default"]
    body = client.get("/api/vocab/model", params={"lang": "de"}).json()
    assert body["fitted"]["labels"] == fitted["labels"] and body["preferences"]["pace"] == "balanced"


def test_a_word_explains_where_it_stands_without_review_dates(client) -> None:
    with client.app.state.engine.begin() as conn:
        word = _word(conn, "Kerze", "learning", 20)
        _met(conn, word, [10, 6])
    body = client.get(f"/api/vocab/words/{word}/progress").json()
    assert body["status"] == "learning" and body["source"] == "manual" and body["days_met"] == 2 and body["next"] == "familiar"
    assert "You set this yourself" in body["message"] and "moves to familiar by itself" in body["message"]
    assert "due" not in body["message"].lower() and "review" not in body["message"].lower()


def test_a_change_made_here_wins_over_an_older_one_sent_later_by_the_phone(client) -> None:
    from app.sync.apply import _word_status

    import time

    phone = HybridClock("PHONE1", now_ms=lambda: int(time.time() * 1000) - 5000)
    older = phone.tick()  # stamped on the phone a few seconds before the change below, sent only now
    with client.app.state.engine.begin() as conn:
        vocab.set_status(conn, "de", "Lampe", "", "known")
        assert _word_status(conn, {"lang": "de", "lemma": "Lampe", "status": "learning"}, older) == "superseded"
        lexeme = conn.execute(text("SELECT id FROM lexemes WHERE lemma = 'Lampe'")).scalar()
        assert _status(conn, lexeme) == "known"


def test_a_lookup_made_offline_keeps_its_time_and_place(client) -> None:
    from app.sync.apply import _lookup as apply_lookup

    when = to_iso(utc_now() - timedelta(hours=5))
    item = client.post("/api/content/text", json={"lang": "de", "title": "T", "text": "Die Lampe ist hell."}).json()["id"]
    with client.app.state.engine.begin() as conn:
        apply_lookup(conn, {"lang": "de", "lemma": "Lampe", "at": when, "content_item_id": item}, "x")
        row = conn.execute(text("SELECT created_at, content_item_id FROM word_events WHERE event = 'lookup' ORDER BY id DESC")).first()
        assert row == (when, item)
        apply_lookup(conn, {"lang": "de", "lemma": "Lampe", "at": "2999-01-01T00:00:00.000Z"}, "y")  # a clock in the future
        latest = conn.execute(text("SELECT created_at FROM word_events WHERE event = 'lookup' ORDER BY id DESC")).scalar()
        assert latest < "2999"
