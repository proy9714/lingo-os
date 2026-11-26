"""Podcasts: reading feeds, following shows, episodes at your level, their audio (no network: fetchers are fakes)."""

from __future__ import annotations

from sqlalchemy import text

from app.ingest import feeds
from app.services import podcasts

FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" xmlns:podcast="https://podcastindex.org/namespace/1.0">
<channel>
  <title>Langsam gesprochen</title>
  <itunes:author>Radio Beispiel</itunes:author>
  <itunes:image href="https://example.org/show.jpg"/>
  <language>de</language>
  <description>Nachrichten, langsam gesprochen.</description>
  <item>
    <title>Folge 2: Das Wetter</title>
    <guid>ep-2</guid>
    <pubDate>Tue, 24 Nov 2026 06:00:00 +0000</pubDate>
    <enclosure url="https://example.org/ep2.mp3" length="5000000" type="audio/mpeg"/>
    <itunes:duration>12:30</itunes:duration>
    <itunes:episode>2</itunes:episode>
    <podcast:transcript url="https://example.org/ep2.vtt" type="text/vtt"/>
  </item>
  <item>
    <title>Folge 1: Der Zug</title>
    <guid>ep-1</guid>
    <pubDate>Mon, 23 Nov 2026 06:00:00 +0000</pubDate>
    <enclosure url="https://example.org/ep1.mp3" length="4000000" type="audio/mpeg"/>
    <itunes:duration>1:05:00</itunes:duration>
    <itunes:image href="https://example.org/ep1.jpg"/>
    <itunes:episode>1</itunes:episode>
  </item>
  <item><title>Ohne Audio</title><guid>no-audio</guid></item>
  <item>
    <title>Zu kurz</title><guid>short</guid>
    <enclosure url="https://example.org/short.mp3" type="audio/mpeg"/><itunes:duration>30</itunes:duration>
  </item>
</channel></rss>"""

VTT = "WEBVTT\n\n" + "\n\n".join(
    f"00:00:{n:02d}.000 --> 00:00:{n + 1:02d}.000\nSatz {n}: Das Wetter ist heute schön und die Kinder spielen im Park." for n in range(10)
)


def fake_fetch(url: str) -> str:
    return {"https://example.org/feed.xml": FEED, "https://example.org/ep2.vtt": VTT}[url]


def test_a_podcast_feed_is_read_with_its_audio_artwork_and_transcripts() -> None:
    show = feeds.parse_podcast(FEED)
    assert (show.title, show.author, show.image, show.language) == ("Langsam gesprochen", "Radio Beispiel", "https://example.org/show.jpg", "de")
    assert [e.guid for e in show.episodes] == ["ep-2", "ep-1", "short"]  # no audio, not an episode
    two, one = show.episodes[0], show.episodes[1]
    assert two.duration_sec == 750 and two.audio_bytes == 5_000_000 and two.number == 2.0
    assert two.transcripts == [("https://example.org/ep2.vtt", "text/vtt")] and two.image == "https://example.org/show.jpg"
    assert one.duration_sec == 3900 and one.image == "https://example.org/ep1.jpg"


def test_following_a_show_adds_its_episodes_measured_or_estimated(client) -> None:
    with client.app.state.engine.begin() as conn:
        result = podcasts.subscribe(conn, "de", "https://example.org/feed.xml", fetch=fake_fetch)
        assert result["added"] == 2 and result["subscribed"] and result["episodes"] == 2  # the 30-second one is skipped
        rows = conn.execute(
            text(
                "SELECT ci.external_id, ci.status, cs.estimated, ci.published_at, ci.collection_index FROM content_items ci "
                "JOIN content_scores cs ON cs.content_item_id = ci.id WHERE ci.type = 'podcast_episode' ORDER BY ci.external_id"
            )
        ).all()
        # episode 2 came with a transcript: measured; episode 1 is estimated until it has one
        assert [(r[0], r[1], r[2]) for r in rows] == [("ep-1", "library", 1), ("ep-2", "library", 0)]
        assert rows[1][3].startswith("2026-11-24") and rows[0][4] == 1.0
        again = podcasts.subscribe(conn, "de", "https://example.org/feed.xml", fetch=fake_fetch)
        assert again["added"] == 0  # nothing twice
    shows = client.get("/api/podcasts", params={"lang": "de"}).json()["shows"]
    assert [(s["title"], s["episodes"], s["image"]) for s in shows] == [("Langsam gesprochen", 2, "https://example.org/show.jpg")]
    episodes = client.get(f"/api/podcasts/{shows[0]['id']}/episodes").json()
    assert [e["external_id"] for e in episodes["items"]] == ["ep-2", "ep-1"]  # newest first
    assert episodes["items"][0]["metadata"]["enclosure_url"] == "https://example.org/ep2.mp3"


def test_episodes_are_suggested_on_the_listen_shelf_not_with_videos(client) -> None:
    with client.app.state.engine.begin() as conn:
        podcasts.subscribe(conn, "de", "https://example.org/feed.xml", fetch=fake_fetch)
    listen = client.get("/api/feed", params={"lang": "de", "shelf": "listen"}).json()["items"]
    watch = client.get("/api/feed", params={"lang": "de", "shelf": "watch"}).json()["items"]
    assert {i["kind"] for i in listen} == {"podcast"} and len(listen) == 2
    assert not any(i["type"] == "podcast_episode" for i in watch)
    estimated = next(i for i in listen if i["estimated"])
    assert "level estimated from the show's other episodes" in estimated["reasons"]  # episode 2 was measured


def test_unfollowing_keeps_what_you_listened_to(client) -> None:
    with client.app.state.engine.begin() as conn:
        show = podcasts.subscribe(conn, "de", "https://example.org/feed.xml", fetch=fake_fetch)["collection_id"]
        heard = conn.execute(text("SELECT id FROM content_items WHERE external_id = 'ep-1'")).scalar()
        conn.execute(
            text("INSERT INTO activity_sessions (language_code, activity, modality, tracking, content_item_id, started_at, active_seconds) "
                 "VALUES ('de', 'podcast', 'listening', 'auto', :i, '2026-11-25T08:00:00.000Z', 300)"),
            {"i": heard},
        )
    assert client.delete(f"/api/podcasts/{show}").json() == {"unsubscribed": True}
    assert client.get("/api/podcasts", params={"lang": "de"}).json()["shows"] == []
    with client.app.state.engine.connect() as conn:
        assert conn.execute(text("SELECT external_id FROM content_items WHERE type = 'podcast_episode'")).scalars().all() == ["ep-1"]


class FakeStream:
    def __init__(self, body: bytes, status: int = 200) -> None:
        self.body, self.status_code = body, status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_bytes(self, size: int):
        for i in range(0, len(self.body), size):
            yield self.body[i : i + size]


class FakeHttp:
    calls = 0

    def stream(self, method, url, **kwargs):  # noqa: ANN001, ANN003, ARG002
        FakeHttp.calls += 1
        return FakeStream(b"ID3" + b"\x00" * 300_000)


def test_episode_audio_is_downloaded_once_and_served_from_here(client, cfg) -> None:
    with client.app.state.engine.begin() as conn:
        podcasts.subscribe(conn, "de", "https://example.org/feed.xml", fetch=fake_fetch)
        item = conn.execute(text("SELECT id FROM content_items WHERE external_id = 'ep-1'")).scalar()
    first = client.get(f"/api/content/{item}/media", follow_redirects=False)
    assert first.status_code == 302 and first.headers["location"] == "https://example.org/ep1.mp3"  # not here yet: the publisher
    with client.app.state.engine.begin() as conn:
        path = podcasts.ensure_local_audio(conn, cfg, item, http=FakeHttp())
        assert podcasts.ensure_local_audio(conn, cfg, item, http=FakeHttp()) == path and FakeHttp.calls == 1
    served = client.get(f"/api/content/{item}/media")
    assert served.status_code == 200 and served.content.startswith(b"ID3")
    info = client.get(f"/api/content/{item}/media/info").json()
    assert info["via"] == "server" and info["bytes"] == path.stat().st_size


def test_searching_the_directory_lists_shows_with_their_feeds(monkeypatch) -> None:
    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {"results": [{"collectionName": "Easy German", "artistName": "Easy German", "feedUrl": "https://example.org/eg.xml",
                                 "artworkUrl600": "https://example.org/eg.jpg", "trackCount": 500}, {"collectionName": "No feed"}]}

    class Http:
        @staticmethod
        def get(url, params, headers, timeout):  # noqa: ANN001, ARG004
            assert params["media"] == "podcast" and params["term"] == "Deutsch lernen"
            return Response()

    results = podcasts.search("de", "", http=Http())
    assert results == [{"title": "Easy German", "author": "Easy German", "feed_url": "https://example.org/eg.xml",
                        "image": "https://example.org/eg.jpg", "genre": None, "episodes": 500}]
