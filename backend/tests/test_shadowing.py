from __future__ import annotations

from app.ingest.subtitles import Cue
from app.services import content
from app.services.shadowing import word_diff


def _video_with_line(client) -> tuple[int, int]:
    with client.app.state.engine.begin() as conn:
        item_id = content.upsert_youtube(conn, "de", "abcdefghijk", title="Test", channel="Kanal", duration=60)
        content.save_transcript(
            conn, item_id, "de", "manual", "vtt",
            [Cue(1000, 3500, "Ich rufe dich morgen an."), Cue(4000, 6000, "Bis dann!")],
        )
        cue_id = content.cues_of(conn, item_id)[0]["id"]
    return item_id, cue_id


def test_word_diff_marks_missed_words() -> None:
    diff = word_diff("de", "Ich rufe dich morgen an.", "ich rufe morgen an")
    assert [(d["text"], d["ok"]) for d in diff] == [("Ich", True), ("rufe", True), ("dich", False), ("morgen", True), ("an.", True)]
    ja = word_diff("ja", "公園に行く。", "公園行く")
    assert [d["ok"] for d in ja] == [True, True, False, True, True, True]  # the full stop is never "missed"


def test_clip_from_a_transcript_line_then_attempts(client) -> None:
    item_id, cue_id = _video_with_line(client)
    clip = client.post("/api/shadow/clips", json={"lang": "de", "text": "Ich rufe dich morgen an.", "content_item_id": item_id, "cue_id": cue_id}).json()
    assert (clip["start_ms"], clip["end_ms"], clip["reference_kind"], clip["external_id"]) == (1000, 3500, "media", "abcdefghijk")
    again = client.post("/api/shadow/clips", json={"lang": "de", "text": "x", "content_item_id": item_id, "cue_id": cue_id}).json()
    assert again["id"] == clip["id"]  # one clip per line

    attempt = client.post(
        f"/api/shadow/clips/{clip['id']}/attempts",
        data={"duration_ms": "2400", "heard": "ich rufe morgen an"},
        files={"audio": ("a.webm", b"\x1a\x45\xdf\xa3fake", "audio/webm;codecs=opus")},
    ).json()
    assert attempt["similarity"] == 0.8 and [d["ok"] for d in attempt["diff"]].count(False) == 1
    audio = client.get(f"/api/shadow/attempts/{attempt['id']}/audio")
    assert audio.status_code == 200 and audio.content.startswith(b"\x1a\x45")

    listed = client.get("/api/shadow/clips", params={"lang": "de"}).json()
    assert listed[0]["practice_count"] == 1 and listed[0]["best"] == 0.8
    assert client.patch(f"/api/shadow/clips/{clip['id']}", json={"favorite": True}).json()["favorite"] is True
    assert client.delete(f"/api/shadow/clips/{clip['id']}").json() == {"deleted": True}
    assert client.get(f"/api/shadow/attempts/{attempt['id']}/audio").status_code == 404


def test_tts_clip_and_bad_audio(client) -> None:
    clip = client.post("/api/shadow/clips", json={"lang": "es", "text": "  Me llamo   Ana.  "}).json()
    assert clip["reference_kind"] == "tts" and clip["text"] == "Me llamo Ana."
    bad = client.post(f"/api/shadow/clips/{clip['id']}/attempts", files={"audio": ("a.txt", b"x", "text/plain")})
    assert bad.status_code == 422


def test_speaking_check_uses_spoken_answers(client) -> None:
    started = client.post("/api/level/de/speaking/start").json()
    item = started["item"]
    step = client.post(
        f"/api/level/dictation/{started['assessment_id']}/answer",
        json={"item_id": item["id"], "typed": item["speak"], "plays": 1},
    ).json()
    assert step["feedback"]["accuracy"] == 1.0
    overview = client.get("/api/level/de/overview").json()
    assert overview["history"] == []  # not finished yet
    # finish it: nine more perfect answers
    for _ in range(9):
        nxt = step["item"]
        step = client.post(
            f"/api/level/dictation/{started['assessment_id']}/answer",
            json={"item_id": nxt["id"], "typed": nxt["speak"], "plays": 1},
        ).json()
    assert step["done"] is True
    skills = client.get("/api/level/de/overview").json()["skills"]
    assert skills["speaking"]["band"] == step["result"]["band"] and "listening" not in skills
