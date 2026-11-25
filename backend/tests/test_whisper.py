"""Transcription with Whisper: off until chosen, then a job that makes and analyses a transcript."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from app.ingest import whisper
from app.ingest.subtitles import Cue
from app.jobs.runner import JobContext
from app.jobs.transcribe import transcribe


def _video(client) -> int:
    with client.app.state.engine.begin() as conn:
        return conn.execute(
            text("INSERT INTO content_items (language_code, type, title, origin, source, external_id, status, duration_sec) "
                 "VALUES ('de', 'youtube', 'Ohne Untertitel', 'user_added', 'youtube', 'nocaptions1', 'library', 90)")
        ).lastrowid


def test_transcription_is_off_until_a_model_is_chosen(client) -> None:
    item = _video(client)
    assert client.get("/api/whisper").json()["model"] is None
    assert client.post(f"/api/content/{item}/transcribe").status_code == 409
    body = client.put("/api/whisper", json={"model": "base"}).json()
    assert body["model"] == "base" and {m["id"] for m in body["models"]} == {"base", "small"}
    assert client.put("/api/whisper", json={"model": "huge"}).status_code == 422
    first = client.post(f"/api/content/{item}/transcribe").json()["job_id"]
    assert client.post(f"/api/content/{item}/transcribe").json()["job_id"] == first  # not twice


def test_the_job_saves_and_analyses_the_transcript(client, monkeypatch, tmp_path) -> None:
    item = _video(client)
    client.put("/api/whisper", json={"model": "base"})
    audio = tmp_path / "a.m4a"
    audio.write_bytes(b"x")
    monkeypatch.setattr(whisper, "ensure_model", lambda cfg, size: Path("model"))
    monkeypatch.setattr(whisper, "youtube_audio", lambda vid, folder: audio)
    monkeypatch.setattr(
        whisper, "transcribe",
        lambda model, path, lang, on_progress=None, duration=None: whisper.Transcription(
            [Cue(0, 2500, "Heute kochen wir zusammen."), Cue(2600, 5000, "Das Essen ist sehr lecker.")], "de", 0.99),
    )
    ctx = JobContext(client.app.state.engine, client.app.state.cfg, None, {"item_id": item})
    assert transcribe(ctx) == {"item_id": item, "lines": 2, "model": "base"}
    body = client.get(f"/api/content/{item}/transcript").json()
    assert [c["text"] for c in body["cues"]] == ["Heute kochen wir zusammen.", "Das Essen ist sehr lecker."]
    assert client.get(f"/api/content/{item}").json()["transcript_kind"] == "whisper"
