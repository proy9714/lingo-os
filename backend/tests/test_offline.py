"""Saving things for offline use: packs for any device, transcripts of videos, recordings downloaded in slices."""

from __future__ import annotations

from app.ingest.subtitles import Cue
from app.services import content


def test_a_browser_can_save_a_text_without_being_a_paired_phone(client) -> None:
    item = client.post("/api/content/text", json={"lang": "de", "title": "Notiz", "text": "Die Kinder spielen im Park."}).json()
    pack = client.get(f"/api/packs/{item['id']}").json()
    assert pack["version"] == 2 and pack["kind"] == "text" and pack["item"]["title"] == "Notiz"
    paragraph = pack["pages"][0]["paragraphs"][0]
    assert paragraph["text"] == "Die Kinder spielen im Park." and paragraph["locator"]  # the reader needs both


def test_a_video_with_a_transcript_saves_as_a_read_along_pack(client) -> None:
    with client.app.state.engine.begin() as conn:
        item_id = content.upsert_youtube(conn, "de", "abcdefghijk", title="Im Park", channel="Kanal", duration=60)
        content.save_transcript(conn, item_id, "de", "manual", "vtt", [Cue(1000, 3500, "Die Kinder spielen im Park.")])
    pack = client.get(f"/api/packs/{item_id}").json()
    assert pack["kind"] == "media" and pack["pages"] == []
    assert pack["item"]["duration_sec"] == 60 and pack["item"]["external_id"] == "abcdefghijk"
    cue = pack["transcript"]["cues"][0]
    assert cue["start_ms"] == 1000 and any(t["display"] == "Park" for t in cue["tokens"])
    assert pack["media"] == {"available": False, "via": "none"}  # a YouTube video itself can't be saved
    assert pack["dictionary"] is not None


def test_a_video_without_a_transcript_cannot_be_saved(client) -> None:
    with client.app.state.engine.begin() as conn:
        item_id = content.upsert_youtube(conn, "de", "zzzzzzzzzzz", title="Leer", channel="Kanal", duration=60)
    response = client.get(f"/api/packs/{item_id}")
    assert response.status_code == 422 and "transcript" in response.json()["detail"]


def test_a_local_recording_downloads_in_slices(client, cfg) -> None:
    folder = cfg.data_dir / "library" / "media" / "de"
    folder.mkdir(parents=True)
    audio = bytes(range(256)) * 20_000  # 5,120,000 bytes: three slices
    (folder / "folge.mp3").write_bytes(audio)
    with client.app.state.engine.begin() as conn:
        content.scan_media(conn, cfg)
    item_id = next(i["id"] for i in client.get("/api/content?lang=de&shelf=watch").json()["items"] if i["title"] == "folge")
    info = client.get(f"/api/content/{item_id}/media/info").json()
    assert info == {"available": True, "bytes": len(audio), "mime": "audio/mpeg", "via": "server"}
    got, offset = b"", 0
    while offset < info["bytes"]:
        part = client.get(f"/api/content/{item_id}/media/chunk", params={"offset": offset})
        assert part.status_code == 200 and int(part.headers["x-total-bytes"]) == len(audio)
        assert len(part.content) <= 2 * 1024 * 1024
        got += part.content
        offset += len(part.content)
    assert got == audio
    assert client.get(f"/api/content/{item_id}/media/chunk", params={"offset": len(audio) + 1}).status_code == 416
    assert client.get(f"/api/content/{item_id}/media/chunk", params={"offset": 0, "length": 3 * 1024 * 1024}).status_code == 422
