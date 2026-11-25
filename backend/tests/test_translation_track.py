"""English under the transcript: YouTube's captions when it gives them, otherwise the AI provider's translation."""

from __future__ import annotations

import json

from sqlalchemy import text

from app.ai.config import parse_ai_config
from app.ai.gateway import Gateway
from app.ingest import youtube
from app.ingest.subtitles import Cue


def _video_with_transcript(client, video_id: str = "abcdefghijk") -> int:
    with client.app.state.engine.begin() as conn:
        item_id = conn.execute(
            text("INSERT INTO content_items (language_code, type, title, origin, source, external_id, status) "
                 "VALUES ('de', 'youtube', 'Video', 'user_added', 'youtube', :v, 'library')"), {"v": video_id}
        ).lastrowid
        transcript = conn.execute(
            text("INSERT INTO transcripts (content_item_id, kind, language_code, is_primary) VALUES (:i, 'manual', 'de', 1)"),
            {"i": item_id},
        ).lastrowid
        for seq, (start, line) in enumerate([(0, "Guten Morgen."), (2000, "Wie geht es dir?")]):
            conn.execute(
                text("INSERT INTO transcript_cues (transcript_id, seq, start_ms, end_ms, text) VALUES (:t, :s, :a, :b, :x)"),
                {"t": transcript, "s": seq, "a": start, "b": start + 1800, "x": line},
            )
    return item_id


def test_youtube_captions_first_and_cached(client, monkeypatch) -> None:
    item_id = _video_with_transcript(client)
    calls = []

    def fake(video_id, to="en"):
        calls.append(video_id)
        return [Cue(0, 1800, "Good morning."), Cue(2000, 3800, "How are you?")]

    monkeypatch.setattr(youtube, "fetch_translation", fake)
    body = client.get(f"/api/content/{item_id}/translation").json()
    assert body["available"] and body["source"] == "youtube" and body["cues"][1]["text"] == "How are you?"
    assert client.get(f"/api/content/{item_id}/translation").json() == body and calls == ["abcdefghijk"]  # cached


def test_ai_translates_when_youtube_refuses(client, monkeypatch) -> None:
    item_id = _video_with_transcript(client)

    def refuse(video_id, to="en"):
        raise youtube.YouTubeError("HTTP Error 429: Too Many Requests")

    monkeypatch.setattr(youtube, "fetch_translation", refuse)
    raw = {"providers": {"cloud": {"kind": "fake"}}, "tasks": {"content.translate": {"use": "cloud", "model": "fake-1"}}}
    gateway = Gateway(parse_ai_config(raw), client.app.state.engine)
    gateway.providers["cloud"].script = lambda req: json.dumps({"lines": ["Good morning.", "How are you?"]})
    client.app.state.ai = gateway
    body = client.get(f"/api/content/{item_id}/translation").json()
    assert body["source"] == "ai" and [c["text"] for c in body["cues"]] == ["Good morning.", "How are you?"]
    assert body["cues"][1]["start_ms"] == 2000

    client.app.state.ai = Gateway(parse_ai_config({"providers": {}, "tasks": {}}), client.app.state.engine)
    other = _video_with_transcript(client, "zyxwvutsrqp")
    off = client.get(f"/api/content/{other}/translation").json()
    assert not off["available"] and "AI translation is off" in off["reason"]
