"""The big catalogue (list channels, estimate, measure), difficulty ratings, and the taste model."""

from __future__ import annotations

from sqlalchemy import text

from app.ingest import youtube
from app.ingest.documents import Document, Section
from app.ingest.feeds import FeedEntry
from app.ingest.subtitles import Cue
from app.services import calibration, catalog, discover, recommend, taste, topup

CUES = [Cue(0, 2000, "Ich gehe heute in den Park."), Cue(2000, 4000, "Dort spielen die Kinder."), Cue(4000, 6000, "Das Wetter ist schön.")]


def _video(conn, title: str, creator: str, *, coverage: float | None = None, watched: int | None = None, duration: int = 600,
           status: str = "library", origin: str = "csv_import", vid: str | None = None, started: str = "2026-11-01T10:00:00.000Z") -> int:
    item_id = conn.execute(
        text(
            "INSERT INTO content_items (language_code, type, title, creator, origin, source, external_id, duration_sec, "
            "analysis_status, status) VALUES ('de', 'youtube', :t, :c, :o, 'youtube', :e, :d, :a, :s)"
        ),
        {"t": title, "c": creator, "o": origin, "e": vid or f"v{abs(hash(title)) % 10**10:010d}", "d": duration,
         "a": "done" if coverage is not None else "pending", "s": status},
    ).lastrowid
    if coverage is not None:
        lo, hi = calibration.window(conn, "de", "youtube")
        band, fit = calibration.band_and_fit(coverage, lo, hi)
        conn.execute(
            text(
                "INSERT INTO content_scores (content_item_id, profile_version, coverage, expected_unknown, i1_score, band) "
                "VALUES (:i, 1, :c, 20, :s, :b)"
            ),
            {"i": item_id, "c": coverage, "s": fit, "b": band},
        )
    if watched is not None:
        conn.execute(
            text(
                "INSERT INTO activity_sessions (language_code, activity, modality, tracking, started_at, active_seconds, "
                "content_item_id) VALUES ('de', 'video', 'listening', 'import', :t, :s, :i)"
            ),
            {"t": started, "s": watched, "i": item_id},
        )
    return item_id


def _listing(n: int, channel: str = "Kanal Eins") -> youtube.Listing:
    return youtube.Listing(f"cat{n:08d}", f"Neue Folge {n}", channel, 600, "https://www.youtube.com/@KanalEins")


def test_channels_you_watch_are_listed_estimated_and_measured(client, cfg) -> None:
    engine = client.app.state.engine
    with engine.begin() as conn:
        for n in range(4):  # you've watched four videos of this channel, all at your level
            _video(conn, f"Alte Folge {n}", "Kanal Eins", coverage=0.93, watched=600)
    looked_up: list[str] = []

    def info(video_id: str) -> youtube.VideoInfo:
        looked_up.append(video_id)
        return youtube.VideoInfo(video_id, "x", "Kanal Eins", 600, "de", None, {"channel_url": "https://www.youtube.com/@KanalEins"})

    listed: list[tuple[str, int, int]] = []
    fetchers = discover.Fetchers(
        info=info,
        channel_uploads=lambda url, limit, start: listed.append((url, limit, start)) or [_listing(n) for n in range(40)],
        search=lambda q, n: [],
        captions=lambda vid, lang: None if vid == "cat00000001" else youtube.Captions("manual", "de", "vtt", CUES),
        feed=lambda url: [],
        pause=lambda s: None,
    )
    stats = discover.discover_language(engine, cfg, "de", fetchers=fetchers, per_run=3, articles=False)
    assert len(looked_up) == 1  # the channel's address, read once from one of your videos
    assert listed == [("https://www.youtube.com/@KanalEins", 60, 1)]
    assert stats["catalogued"] == 40 and stats["checked"] == 3
    page = client.get("/api/feed", params={"lang": "de", "shelf": "watch", "limit": 60}).json()
    assert page["total"] >= 37 and page["estimated"] >= 34  # most are estimated from the channel; three were measured
    estimated = next(i for i in page["items"] if i["estimated"])
    assert estimated["band"] and "level estimated from the channel" in estimated["reasons"]
    assert estimated["level_basis"] == "channel3"
    with engine.connect() as conn:
        status = conn.execute(text("SELECT status FROM content_items WHERE external_id = 'cat00000001'")).scalar()
        depth = conn.execute(text("SELECT json_extract(config_json, '$.depth') FROM content_sources")).scalar()
    assert status in ("dismissed", "candidate")
    assert depth == 60  # next time, a page further back

    # a second run doesn't look the channel up again, and lists deeper
    listed.clear()
    discover.discover_language(engine, cfg, "de", fetchers=fetchers, per_run=1, articles=False)
    assert len(looked_up) == 1 and listed == [("https://www.youtube.com/@KanalEins", 120, 1)]


def test_unknown_channels_are_measured_before_they_are_suggested(client, cfg) -> None:
    engine = client.app.state.engine
    fetchers = discover.Fetchers(
        search=lambda q, n: [youtube.Listing("unknown0001", "Etwas Neues", "Fremder Kanal", 600, "https://www.youtube.com/@Fremd")],
        channel_uploads=lambda url, limit, start: [], info=lambda v: None, feed=lambda url: [],
        captions=lambda vid, lang: youtube.Captions("manual", "de", "vtt", CUES), pause=lambda s: None,
    )
    catalog.add_listings(engine, "de", [(v, "search: x") for v in fetchers.search("x", 1)], discover.DEFAULTS)
    with engine.begin() as conn:
        assert catalog.estimate_scores(conn, "de") == 0  # nothing known about the channel: no guess
    assert client.get("/api/feed", params={"lang": "de", "shelf": "watch"}).json()["total"] == 0
    keep = ["too_easy", "comfortable", "i_plus_1", "stretch", "too_hard"]
    result = catalog.verify(engine, "de", fetchers, keep, limit=5)
    assert result["kept"] == 1
    with engine.begin() as conn:  # measured at your level: its other videos get listed next time
        conn.execute(text("UPDATE content_scores SET band = 'i_plus_1'"))
        assert catalog.promote_channels(conn, "de") == 1
        assert catalog.promote_channels(conn, "de") == 0
        sources = conn.execute(text("SELECT name, origin FROM content_sources")).all()
    assert sources == [("Fremder Kanal", "discovered")]


def test_refusal_pauses_youtube_but_not_articles(client, cfg) -> None:
    engine = client.app.state.engine

    def refuse(*args):
        raise youtube.YouTubeError("Sign in to confirm you're not a bot")

    fetchers = discover.Fetchers(
        search=refuse, channel_uploads=refuse, info=refuse, captions=refuse, pause=lambda s: None,
        feed=lambda url: [FeedEntry("Kinder", "https://kinder.example/1", None)],
        article=lambda url: Document("Kinder", None, "de", [Section(None, ["Die Kinder spielen im Park."])]),
    )
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO content_sources (language_code, kind, name, target) VALUES ('de', 'youtube_channel', 'K', 'https://y/@k')"))
    first = discover.discover_language(engine, cfg, "de", fetchers=fetchers)
    assert first["stopped_early"] is True
    with engine.connect() as conn:
        assert catalog.youtube_refused_recently(conn)
    second = discover.discover_language(engine, cfg, "de", fetchers=fetchers)
    assert "YouTube refused recently" in " ".join(second["errors"])
    with engine.begin() as conn:
        top = topup.maybe_top_up(conn, "de", force=True)
    assert "watch" not in top.get("shelves", [])


def test_difficulty_ratings_move_your_level(client) -> None:
    engine = client.app.state.engine
    with engine.begin() as conn:
        ids = [_video(conn, f"Video {n}", "K", coverage=0.93, watched=600) for n in range(3)]
        before = calibration.window(conn, "de", "youtube")
        fit_before = conn.execute(text("SELECT i1_score FROM content_scores WHERE content_item_id = :i"), {"i": ids[2]}).scalar()
    hard = client.put(f"/api/content/{ids[0]}/difficulty", json={"value": 5}).json()
    assert hard["label"] == "Very hard" and hard["ideal_after"] > hard["ideal_before"]
    assert "easier" in hard["message"]
    client.put(f"/api/content/{ids[1]}/difficulty", json={"value": 5})
    with engine.connect() as conn:
        after = calibration.window(conn, "de", "youtube")
        reading = calibration.window(conn, "de", "text")
        fit_after = conn.execute(text("SELECT i1_score FROM content_scores WHERE content_item_id = :i"), {"i": ids[2]}).scalar()
    assert after[0] > before[0]  # the window moved toward easier videos
    assert reading == (calibration.DEFAULT_IDEAL["reading"] - 0.05, calibration.DEFAULT_IDEAL["reading"] + 0.05)  # reading untouched
    assert fit_after < fit_before  # 93% known now fits you less well: you get easier videos first
    easy = client.put(f"/api/content/{ids[0]}/difficulty", json={"value": 1}).json()
    assert easy["ideal_after"] < hard["ideal_after"]
    summary = client.get("/api/taste", params={"lang": "de"}).json()["calibration"]["listening"]
    assert summary["ratings"] == 2 and summary["counts"]["Very easy"] == 1
    assert client.put(f"/api/content/{ids[0]}/difficulty", json={"value": 9}).status_code == 422


def test_taste_learns_channels_and_lengths(client) -> None:
    engine = client.app.state.engine
    with engine.begin() as conn:
        for n in range(6):  # you finish this channel's videos
            _video(conn, f"Geliebt {n}", "Lieblingskanal", coverage=0.93, watched=590)
        for n in range(4):  # and leave this one almost at once
            _video(conn, f"Langweilig {n}", "Anderer Kanal", coverage=0.93, watched=20)
        liked = _video(conn, "Neu A", "Lieblingskanal", coverage=0.93, status="candidate", origin="scraper")
        other = _video(conn, "Neu B", "Anderer Kanal", coverage=0.93, status="candidate", origin="scraper")
        fresh = _video(conn, "Neu C", "Ganz neu", coverage=0.93, status="candidate", origin="scraper")
        taste.invalidate("de")
        prof = taste.profile(conn, "de")
    assert prof.channel_affinity("Lieblingskanal") > 0.5 > prof.channel_affinity("Anderer Kanal")
    assert prof.channel_affinity("Anderer Kanal") < 0
    recommend.invalidate()
    items = client.get("/api/feed", params={"lang": "de", "shelf": "watch"}).json()["items"]
    order = [i["id"] for i in items]
    assert order.index(liked) < order.index(fresh) < order.index(other)
    first = items[0]
    assert any("you often watch Lieblingskanal" in r for r in first["reasons"])
    summary = client.get("/api/taste", params={"lang": "de"}).json()
    assert summary["channels"][0]["name"] == "Lieblingskanal" and summary["less_of"][0]["name"] == "Anderer Kanal"


def test_not_interested_teaches_the_taste_model(client) -> None:
    engine = client.app.state.engine
    with engine.begin() as conn:
        a = _video(conn, "Kochen 1", "Kochkanal", coverage=0.93, status="candidate", origin="scraper")
        _video(conn, "Kochen 2", "Kochkanal", coverage=0.93, status="candidate", origin="scraper")
    client.post(f"/api/content/{a}/dismiss")
    with engine.connect() as conn:
        assert taste.profile(conn, "de").channel_affinity("Kochkanal") < 0


def test_good_feeds_get_their_archive_read(client, cfg, monkeypatch) -> None:
    monkeypatch.setattr(
        discover, "load_sources",
        lambda cfg: {"defaults": {**discover.DEFAULTS, "keep_bands": ["too_easy", "comfortable", "i_plus_1", "stretch", "too_hard"]},
                     "languages": {"de": {"feeds": [{"name": "Kinder", "url": "https://kinder.example/feed/"}]}}},
    )
    requested: list[str] = []

    def feed(url: str) -> list[FeedEntry]:
        requested.append(url)
        page = int(url.split("paged=")[1]) if "paged=" in url else 1
        return [FeedEntry(f"Artikel {page}-{k}", f"https://kinder.example/{page}/{k}", None) for k in range(3)]

    fetchers = discover.Fetchers(
        feed=feed, pause=lambda s: None,
        article=lambda url: Document(url, None, "de", [Section(None, ["Die Kinder spielen heute im Park."])]),
    )
    stats = discover.discover_language(client.app.state.engine, cfg, "de", fetchers=fetchers, videos=False)
    assert requested[:3] == ["https://kinder.example/feed/", "https://kinder.example/feed/?paged=2", "https://kinder.example/feed/?paged=3"]
    assert stats["articles_added"] == 9


def test_videos_about_another_language_are_left_out() -> None:
    assert catalog.other_language_title("Japanese Basic II - 51 - Give it to him", "de")
    assert catalog.other_language_title("Learn French with stories", "de")
    assert not catalog.other_language_title("Easy German 300 | Street interviews", "de")
    assert not catalog.other_language_title("Ein Tag in Berlin (English subtitles)", "de")
    assert not catalog.other_language_title("Japanisch für Deutsche: Folge 3 | Deutsch", "de")  # names German too
    assert catalog.other_language_title("Aprende alemán: Lección 1", "es")
    assert not catalog.other_language_title("Mi vida en Japón", "es")


def test_already_watched_leaves_the_suggestions_and_can_be_undone(client) -> None:
    engine = client.app.state.engine
    with engine.begin() as conn:
        a = _video(conn, "Reise 1", "Reisekanal", coverage=0.93, status="candidate", origin="scraper")
        conn.execute(text("UPDATE content_items SET progress = 0.4 WHERE id = :i"), {"i": a})

    def feed_ids() -> list[int]:
        return [i["id"] for i in client.get("/api/feed", params={"lang": "de", "shelf": "watch"}).json()["items"]]

    def watched_ids() -> list[int]:
        params = {"lang": "de", "shelf": "watch", "state": "watched"}
        return [i["id"] for i in client.get("/api/content", params=params).json()["items"]]

    assert a in feed_ids() and a not in watched_ids()
    marked = client.post(f"/api/content/{a}/watched", json={"watched": True}).json()
    assert marked["status"] == "finished" and marked["metadata"]["marked_watched"] == 1
    assert a not in feed_ids() and a in watched_ids()

    undone = client.post(f"/api/content/{a}/watched", json={"watched": False}).json()
    assert undone["status"] == "candidate" and undone["progress"] == 0.4 and "marked_watched" not in undone["metadata"]
    assert a in feed_ids() and a not in watched_ids()
    assert client.post("/api/content/999999/watched", json={"watched": True}).status_code == 404


def test_a_new_learner_still_gets_the_closest_suggestions(client) -> None:
    """Everything found is too hard for a beginner: the list shows the closest anyway, instead of nothing."""
    engine = client.app.state.engine
    with engine.begin() as conn:
        for n in range(3):
            _video(conn, f"Schwer {n}", f"Kanal {n}", coverage=0.6, status="candidate", origin="scraper")
        band = conn.execute(text("SELECT DISTINCT band FROM content_scores")).scalar()
    assert band == "too_hard"
    feed = client.get("/api/feed", params={"lang": "de", "shelf": "watch"}).json()
    assert feed["total"] == 3
    assert all("the closest to your level found so far" in i["reasons"] for i in feed["items"])
    # but they don't count as enough: the background search keeps looking
    assert client.get("/api/discover/pool", params={"lang": "de"}).json()["pools"]["watch"] == 0


def test_learner_channels_from_the_wiki_are_estimated_before_measuring(client) -> None:
    engine = client.app.state.engine
    with engine.begin() as conn:
        source = conn.execute(
            text(
                "INSERT INTO content_sources (language_code, kind, name, target, origin, enabled) "
                "VALUES ('de', 'youtube_channel', 'Lernkanal', 'https://www.youtube.com/@Lernkanal', 'ci_wiki', 1)"
            )
        ).lastrowid
        item = _video(conn, "Folge 1", "Lernkanal", status="candidate", origin="scraper")
        conn.execute(text("UPDATE content_items SET source_id = :s WHERE id = :i"), {"s": source, "i": item})
        assert catalog.estimate_scores(conn, "de", [item]) == 1
        basis = conn.execute(text("SELECT json_extract(metadata_json, '$.level_basis') FROM content_items WHERE id = :i"), {"i": item}).scalar()
    assert basis == "language"


def test_youtube_refusals_pause_longer_each_time_and_reset(client, monkeypatch) -> None:
    from datetime import timedelta

    from app.db import settings_store
    from app.timeutil import to_iso, utc_now

    engine = client.app.state.engine

    def refused_ago(hours: float) -> bool:
        with engine.begin() as conn:
            settings_store.put(conn, catalog.REFUSAL_KEY, to_iso(utc_now() - timedelta(hours=hours)))
            return catalog.youtube_refused_recently(conn)

    catalog._mark_refused(engine)
    assert refused_ago(0.5) and not refused_ago(1.5)  # first refusal: one hour
    catalog._mark_refused(engine)
    assert refused_ago(1.5) and not refused_ago(2.5)  # second in a row: two hours
    catalog._mark_answered(engine)
    catalog._mark_refused(engine)
    assert not refused_ago(1.5)  # answered in between: back to one hour


def test_watch_later_keeps_a_list_until_it_is_watched(client) -> None:
    engine = client.app.state.engine
    with engine.begin() as conn:
        a = _video(conn, "Später 1", "Kanal A", coverage=0.93, status="candidate", origin="scraper")
        b = _video(conn, "Später 2", "Kanal B", coverage=0.93, status="candidate", origin="scraper")

    def later_ids() -> list[int]:
        params = {"lang": "de", "shelf": "watch", "state": "later"}
        return [i["id"] for i in client.get("/api/content", params=params).json()["items"]]

    assert later_ids() == []
    saved = client.post(f"/api/content/{a}/later", json={"later": True}).json()
    assert saved["metadata"]["saved_at"] and saved["status"] == "library"  # kept: never pruned as a stale suggestion
    client.post(f"/api/content/{b}/later", json={"later": True})
    assert later_ids() == [b, a]  # most recently saved first
    pick = next(i for i in client.get("/api/feed", params={"lang": "de", "shelf": "watch"}).json()["items"] if i["id"] == a)
    assert pick["later"] is True
    client.post(f"/api/content/{b}/watched", json={"watched": True})
    assert later_ids() == [a]  # watched: off the list
    client.post(f"/api/content/{a}/later", json={"later": False})
    assert later_ids() == []
    assert client.post("/api/content/999999/later", json={"later": True}).status_code == 404
