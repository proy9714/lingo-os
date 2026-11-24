"""Words move up by themselves when met on several days without being looked up; your own changes always win."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import text

from app.services import vocab, word_progress
from app.timeutil import to_iso, utc_now


def _ago(days: float) -> str:
    return to_iso(utc_now() - timedelta(days=days))


def _word(conn, lemma: str, status: str, changed_days_ago: float) -> int:
    vocab.set_status(conn, "de", lemma, "", status)
    lexeme = conn.execute(text("SELECT id FROM lexemes WHERE lemma = :l"), {"l": lemma}).scalar()
    conn.execute(text("UPDATE user_words SET status_changed_at = :t, last_lookup_at = NULL WHERE lexeme_id = :w"),
                 {"t": _ago(changed_days_ago), "w": lexeme})
    return lexeme


def _met(conn, lexeme: int, days_ago: list[float], times: int = 2, kind: str = "youtube") -> None:
    item = conn.execute(
        text("INSERT INTO content_items (language_code, type, title, source, origin, status) VALUES ('de', :k, 'Video', 'local', 'user_added', 'library')"),
        {"k": kind},
    ).lastrowid
    conn.execute(text("INSERT INTO content_lemmas (content_item_id, lexeme_id, count) VALUES (:i, :w, :n)"), {"i": item, "w": lexeme, "n": times})
    for d in days_ago:
        conn.execute(
            text(
                "INSERT INTO activity_sessions (language_code, activity, modality, tracking, content_item_id, started_at, "
                "active_seconds) VALUES ('de', 'video', 'listening', 'auto', :i, :t, 600)"
            ),
            {"i": item, "t": _ago(d)},
        )


def _status(conn, lexeme: int) -> str:
    return conn.execute(text("SELECT status FROM user_words WHERE lexeme_id = :w"), {"w": lexeme}).scalar()


def test_a_learning_word_met_on_three_days_becomes_familiar(client) -> None:
    with client.app.state.engine.begin() as conn:
        word = _word(conn, "Bahnhof", "learning", 20)
        _met(conn, word, [10, 6, 3])
        moves = word_progress.promote(conn, "de")
        assert [(m["lexeme_id"], m["from"], m["to"]) for m in moves] == [(word, "learning", "familiar")]
        assert moves[0]["days"] == 3 and moves[0]["times"] == 6
        assert _status(conn, word) == "familiar"
    recent = client.get("/api/vocab/moves", params={"lang": "de"}).json()
    assert recent["moves"][0]["to"] == "familiar" and recent["moves"][0]["status"] == "familiar"


def test_two_days_or_a_recent_lookup_is_not_enough(client) -> None:
    with client.app.state.engine.begin() as conn:
        few = _word(conn, "Fahrrad", "learning", 20)
        _met(conn, few, [5, 2])
        looked = _word(conn, "Schlüssel", "learning", 20)
        _met(conn, looked, [10, 6, 3])
        conn.execute(text("UPDATE user_words SET last_lookup_at = :t WHERE lexeme_id = :w"), {"t": _ago(0.5), "w": looked})
        assert word_progress.promote(conn, "de") == []
        assert _status(conn, few) == "learning" and _status(conn, looked) == "learning"


def test_familiar_to_known_needs_a_week_and_no_lookups(client) -> None:
    with client.app.state.engine.begin() as conn:
        quick = _word(conn, "Tisch", "familiar", 10)
        _met(conn, quick, [4, 3, 2])  # three days, but within a few days: not yet
        slow = _word(conn, "Stuhl", "familiar", 15)
        _met(conn, slow, [12, 7, 2])
        moves = {m["lexeme_id"]: m["to"] for m in word_progress.promote(conn, "de")}
        assert moves == {slow: "known"}
        assert _status(conn, quick) == "familiar" and _status(conn, slow) == "known"


def test_moving_a_word_back_yourself_resets_the_evidence(client) -> None:
    with client.app.state.engine.begin() as conn:
        word = _word(conn, "Fenster", "learning", 20)
        _met(conn, word, [10, 6, 3])
        word_progress.promote(conn, "de")
        vocab.set_status(conn, "de", "Fenster", "", "learning")  # you disagree: back to learning
        assert word_progress.promote(conn, "de") == []  # the old encounters were before your change
        assert _status(conn, word) == "learning"


def test_whole_books_dont_count(client) -> None:
    with client.app.state.engine.begin() as conn:
        word = _word(conn, "Kapitel", "learning", 20)
        _met(conn, word, [10, 6, 3], kind="epub")
        assert word_progress.promote(conn, "de") == []
