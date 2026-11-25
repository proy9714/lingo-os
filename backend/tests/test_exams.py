"""A passed official exam anchors the starting estimate more firmly than a guess, and fades after two years."""

from __future__ import annotations

from datetime import date

from app.engine import exams
from app.engine.profile import SELF_LEVEL_WORDS, get_profile


def test_an_exam_sets_the_starting_point(client) -> None:
    body = client.put("/api/languages/de/level", json={"level": "A2"}).json()
    assert {e["id"] for e in body["exams"]} >= {"goethe", "telc", "testdaf", "other"}
    with client.app.state.engine.connect() as conn:
        guessed = get_profile(conn, "de")

    body = client.put("/api/languages/de/exam", json={"exam": "goethe", "level": "B2", "passed_on": "2026-03-01"}).json()
    assert body["exam"]["name"] == "Goethe-Zertifikat" and body["exam"]["level"] == "B2" and body["has_start"]
    with client.app.state.engine.connect() as conn:
        anchored = get_profile(conn, "de")
    assert anchored["vocab_size"] > guessed["vocab_size"]  # B2 outranks the A2 guess
    assert abs(anchored["vocab_size"] - SELF_LEVEL_WORDS["B2"]) < SELF_LEVEL_WORDS["B2"] * 0.5
    assert anchored["confidence"] > guessed["confidence"] and not anchored["measured"]

    assert client.put("/api/languages/de/exam", json={"exam": "jlpt", "level": "N3"}).status_code == 422  # not for German
    assert client.put("/api/languages/de/exam", json={"exam": "goethe", "level": "Z9"}).status_code == 422
    assert client.put("/api/languages/de/exam", json={"exam": "goethe", "level": "B1", "passed_on": "2999-01-01"}).status_code == 422
    assert client.put("/api/languages/ja/exam", json={"exam": "jlpt", "level": "N3"}).json()["exam"]["level"] == "N3"
    assert client.put("/api/languages/de/exam", json={"exam": None}).json()["exam"] is None


def test_exams_fade_after_two_years() -> None:
    today = date(2026, 11, 25)
    assert exams.weight("2025-01-01", today) == 1.0
    assert 0 < exams.weight("2024-05-01", today) < 1
    assert exams.weight("2020-01-01", today) == 0.0 and exams.weight(None, today) == 1.0
    assert exams.resolve("zh", "hsk", "4")["level"] == "B1" and exams.resolve("ko", "topik", "6")["level"] == "C2"
