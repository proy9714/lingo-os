from __future__ import annotations

from app.level.ctest import LEVELS, _band, make_gaps, score_answer
from app.level.ctest_texts import TEXTS


def test_c_test_gaps_follow_the_rule() -> None:
    passage = TEXTS["de"]["B1"]
    segments = make_gaps(passage)
    gaps = [s for s in segments if "gap" in s]
    assert 8 <= len(gaps) <= 12
    for gap in gaps:  # the larger half is removed
        word = gap["shown"] + gap["missing"]
        assert len(gap["shown"]) == len(word) // 2
    rebuilt = "".join(s["text"] if "text" in s else s["shown"] + s["missing"] for s in segments)
    assert rebuilt == passage  # nothing lost or duplicated
    first_sentence = passage.split(". ")[0]
    assert segments[0]["text"].startswith(first_sentence)  # first sentence intact


def test_scoring_gives_half_credit_for_accents_only() -> None:
    assert score_answer("käufer", "käufer") == 1.0
    assert score_answer("käufer", "KÄUFER") == 1.0
    assert score_answer("käufer", "kaufer") == 0.5
    assert score_answer("ße", "sse") == 0.5
    assert score_answer("käufer", "kaufen") == 0.0


def test_band_from_scores() -> None:
    assert _band({"A2": 0.9, "B1": 0.8, "B2": 0.5, "C1": 0.2}) == ("B1", "B1", "B2")
    assert _band({"A2": 0.7, "B1": 0.3, "B2": 0.1, "C1": 0.0}) == ("A2", "A1", "A2")
    assert _band({"A2": 0.2, "B1": 0.1, "B2": 0.0, "C1": 0.0}) == ("A1", "A1", "A1")
    assert _band({level: 1.0 for level in LEVELS}) == ("C1", "C1", "C1")


def test_c_test_api_flow(client) -> None:
    started = client.post("/api/level/de/ctest/start").json()
    gaps = [s for p in started["passages"] for s in p["segments"] if "gap" in s]
    assert all("missing" not in g for g in gaps)  # answers never leave the server
    perfect = {}
    for passage in TEXTS["de"].values():
        perfect.update({})
    # answer everything correctly by re-deriving the expected halves
    expected = [g["missing"] for level in LEVELS for g in make_gaps(TEXTS["de"][level]) if "gap" in g]
    answers = {gap["gap"]: missing for gap, missing in zip(gaps, expected)}
    result = client.post(f"/api/level/ctest/{started['assessment_id']}/submit", json={"answers": answers}).json()
    assert result["result"]["band"] == "C1" and result["result"]["overall"] == 1.0
    again = client.post(f"/api/level/ctest/{started['assessment_id']}/submit", json={"answers": answers})
    assert again.status_code == 422
    overview = client.get("/api/level/de/overview").json()
    assert overview["skills"]["reading"]["band"] == "C1"


def test_japanese_c_test_not_offered_yet(client) -> None:
    assert client.post("/api/level/ja/ctest/start").status_code == 422
    assert client.get("/api/level/ja/overview").json()["ctest_available"] is False


def test_vocab_test_needs_a_dictionary(client) -> None:
    response = client.post("/api/level/es/vocab/start")
    assert response.status_code == 422 and "dictionary" in response.json()["detail"]


def test_starting_profile_comes_from_hours(client) -> None:
    profile = client.get("/api/level/de/overview").json()["profile"]
    assert profile["measured"] is False and profile["vocab_size"] >= 100
