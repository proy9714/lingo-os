from __future__ import annotations

import json

from app.ingest.subtitles import parse_json3, parse_vtt
from app.ingest.youtube import parse_video_id
from app.level.dictation import score

AUTO_JSON3 = json.dumps(
    {
        "events": [
            {"tStartMs": 1000, "dDurationMs": 4720, "segs": [{"utf8": "Hallo,"}, {"utf8": " ich", "tOffsetMs": 640}, {"utf8": " bin", "tOffsetMs": 800}, {"utf8": " Kari.", "tOffsetMs": 960}]},
            {"tStartMs": 3270, "dDurationMs": 2450, "aAppend": 1, "segs": [{"utf8": "\n"}]},
            {"tStartMs": 3280, "dDurationMs": 5120, "segs": [{"utf8": "Und", "isSpeakerChange": 1}, {"utf8": " ich", "tOffsetMs": 360}, {"utf8": " bin", "tOffsetMs": 1320}, {"utf8": " Janosch.", "tOffsetMs": 1560}]},
        ]
    }
)


def test_auto_captions_become_sentence_cues() -> None:
    cues = parse_json3(AUTO_JSON3)
    assert [c.text for c in cues] == ["Hallo, ich bin Kari.", "Und ich bin Janosch."]
    assert cues[0].start_ms == 1000 and cues[1].start_ms == 3280
    assert len(cues[0].words) == 4


def test_vtt_parsing_drops_tags_noise_and_repeats() -> None:
    vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:02.500\n<c>Hola</c> mundo\n\n00:00:02.500 --> 00:00:03.000\nHola mundo\n\n00:00:03.000 --> 00:00:04.000\n[Música]\n"
    cues = parse_vtt(vtt)
    assert [(c.start_ms, c.end_ms, c.text) for c in cues] == [(1000, 3000, "Hola mundo")]


def test_video_ids_from_links() -> None:
    for link in ("https://www.youtube.com/watch?v=6tAMFeWl55o", "https://youtu.be/6tAMFeWl55o?t=3", "6tAMFeWl55o"):
        assert parse_video_id(link) == "6tAMFeWl55o"
    assert parse_video_id("https://example.com/") is None


def test_dictation_scoring_ignores_case_accents_and_punctuation() -> None:
    assert score("de", "Wo ist der nächste Bahnhof?", "wo ist der nachste bahnhof") == 1.0
    assert score("es", "¿Dónde está la estación?", "donde esta la") == 0.75
    assert score("ja", "駅はどこですか。", "えきはどこですか") == 1.0  # kana input is fine


def test_heartbeats_build_one_session_and_track_progress(client) -> None:
    body = {"lang": "de", "activity": "video", "session": "abcd1234-test", "seconds": 15}
    first = client.post("/api/activity/heartbeat", json=body).json()
    second = client.post("/api/activity/heartbeat", json={**body, "seconds": 100}).json()  # credited at most 30
    assert first["session_id"] == second["session_id"] and second["active_seconds"] == 45
    assert client.post("/api/activity/heartbeat", json={**body, "activity": "flashcards"}).status_code == 422
    assert client.get("/api/stats/today", params={"lang": "de"}).json()["today_minutes"] == 1


def test_dictation_flow(client) -> None:
    started = client.post("/api/level/de/dictation/start").json()
    step = started
    for _ in range(10):
        step = client.post(
            f"/api/level/dictation/{started['assessment_id']}/answer",
            json={"item_id": step["item"]["id"], "typed": step["item"]["speak"], "plays": 1},
        ).json()
        if step["done"]:
            break
    assert step["done"] and step["result"]["band"] == "C1" and step["result"]["overall"] == 1.0
