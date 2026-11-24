from __future__ import annotations

import edge_tts
import pytest

from app.services import tts

VOICES = [
    {"ShortName": "de-DE-TanjaNeural", "Gender": "Female", "Locale": "de-DE"},
    {"ShortName": "de-DE-ChristophNeural", "Gender": "Male", "Locale": "de-DE"},
    {"ShortName": "de-AT-IngridNeural", "Gender": "Female", "Locale": "de-AT"},
    {"ShortName": "ja-JP-NanamiNeural", "Gender": "Female", "Locale": "ja-JP"},
    {"ShortName": "en-US-AriaNeural", "Gender": "Female", "Locale": "en-US"},
]


@pytest.fixture
def fake_voices(monkeypatch):
    """A stand-in for Microsoft's voice service: records what it was asked to say."""
    said: list[tuple[str, str, str]] = []
    tts._voices = None

    async def list_voices():
        return VOICES

    class Communicate:
        def __init__(self, text, voice, *, rate="+0%", **_):
            self.args = (text, voice, rate)

        async def save(self, path):
            said.append(self.args)
            with open(path, "wb") as out:
                out.write(b"ID3fake-mp3")

    monkeypatch.setattr(edge_tts, "list_voices", list_voices)
    monkeypatch.setattr(edge_tts, "Communicate", Communicate)
    yield said
    tts._voices = None


def test_speaks_in_a_native_voice_and_caches_the_clip(client, fake_voices) -> None:
    first = client.get("/api/tts", params={"lang": "de", "text": "Ich rufe dich  morgen an.", "rate": 0.9})
    assert first.status_code == 200 and first.headers["content-type"] == "audio/mpeg"
    assert first.content == b"ID3fake-mp3"
    # the language's own voice (German from Germany, female first), never an English one
    assert fake_voices == [("Ich rufe dich morgen an.", "de-DE-TanjaNeural", "-10%")]
    again = client.get("/api/tts", params={"lang": "de", "text": "Ich rufe dich morgen an.", "rate": 0.9})
    assert again.status_code == 200 and len(fake_voices) == 1  # served from the cache


def test_voice_list_and_choice(client, fake_voices) -> None:
    listed = client.get("/api/tts/voices", params={"lang": "de"}).json()
    assert [v["id"] for v in listed["voices"]] == ["de-DE-TanjaNeural", "de-DE-ChristophNeural", "de-AT-IngridNeural"]
    assert listed["voice"] == "de-DE-TanjaNeural" and listed["engine"] == "neural"
    assert listed["voices"][1]["name"] == "Christoph"

    assert client.put("/api/tts/settings", json={"lang": "de", "voice": "de-DE-ChristophNeural"}).status_code == 200
    assert client.get("/api/tts/voices", params={"lang": "de"}).json()["voice"] == "de-DE-ChristophNeural"
    client.get("/api/tts", params={"lang": "de", "text": "Hallo"})
    assert fake_voices[-1][1] == "de-DE-ChristophNeural"

    # a Japanese voice can't be chosen for German
    assert client.put("/api/tts/settings", json={"lang": "de", "voice": "ja-JP-NanamiNeural"}).status_code == 422
    assert client.put("/api/tts/settings", json={"engine": "device"}).json()["engine"] == "device"


def test_unreachable_service_is_a_clear_error(client, monkeypatch, fake_voices) -> None:
    class Broken:
        def __init__(self, *args, **kwargs):
            pass

        async def save(self, path):
            raise OSError("no network")

    monkeypatch.setattr(edge_tts, "Communicate", Broken)
    response = client.get("/api/tts", params={"lang": "ja", "text": "こんにちは"})
    assert response.status_code == 503 and "unavailable" in response.json()["detail"]
    assert client.get("/api/tts", params={"lang": "xx", "text": "hi"}).status_code == 422


def test_rate_is_sent_as_a_percentage() -> None:
    assert tts.rate_text(1.0) == "+0%" and tts.rate_text(0.75) == "-25%" and tts.rate_text(1.25) == "+25%"
