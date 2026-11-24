"""Suggestion feeds (infinite scroll), background top-ups, article discovery across feeds, and tutor topics."""

from __future__ import annotations

from sqlalchemy import text

from app.ingest.documents import Document, Section
from app.ingest.feeds import FeedEntry, clean_title, parse_feed
from app.services import discover, topup
from app.services.recommend import spread_creators


def _item(conn, title: str, *, kind: str = "youtube", creator: str = "Kanal", score: float = 0.8, status: str = "library",
          origin: str = "scraper", image: str | None = None) -> int:
    meta = '{"image": "%s"}' % image if image else "{}"
    item_id = conn.execute(
        text(
            "INSERT INTO content_items (language_code, type, title, creator, origin, source, external_id, analysis_status, "
            "status, metadata_json) VALUES ('de', :k, :t, :c, :o, :src, :e, 'done', :s, :m)"
        ),
        {"k": kind, "t": title, "c": creator, "o": origin, "src": "youtube" if kind == "youtube" else "web",
         "e": f"x-{title}", "s": status, "m": meta},
    ).lastrowid
    conn.execute(
        text(
            "INSERT INTO content_scores (content_item_id, profile_version, coverage, expected_unknown, i1_score, band) "
            "VALUES (:i, 1, 0.93, 12, :s, 'i_plus_1')"
        ),
        {"i": item_id, "s": score},
    )
    return item_id


def _watch(conn, item_id: int) -> None:
    conn.execute(
        text(
            "INSERT INTO activity_sessions (language_code, activity, modality, tracking, started_at, active_seconds, "
            "content_item_id) VALUES ('de', 'video', 'listening', 'import', '2026-11-01T10:00:00.000Z', 600, :i)"
        ),
        {"i": item_id},
    )


def test_feed_pages_through_suggestions_without_watched_videos(client) -> None:
    engine = client.app.state.engine
    with engine.begin() as conn:
        ids = [_item(conn, f"Video {n:02d}", creator=f"Kanal {n % 3}", score=0.9 - n * 0.01) for n in range(30)]
        _watch(conn, ids[0])
        _item(conn, "Artikel", kind="article", image="https://img.example/a.jpg")
    first = client.get("/api/feed", params={"lang": "de", "shelf": "watch", "limit": 12}).json()
    assert first["total"] == 29 and len(first["items"]) == 12 and first["next_offset"] == 12
    titles = [i["title"] for i in first["items"]]
    assert "Video 00" not in titles  # watched: never suggested
    rest: list[str] = []
    offset = first["next_offset"]
    while offset is not None:
        page = client.get("/api/feed", params={"lang": "de", "shelf": "watch", "limit": 12, "offset": offset}).json()
        rest += [i["title"] for i in page["items"]]
        offset = page["next_offset"]
    assert len(set(titles + rest)) == 29  # no repeats across pages
    reading = client.get("/api/feed", params={"lang": "de", "shelf": "read"}).json()
    assert [(i["title"], i["image"], i["kind"]) for i in reading["items"]] == [("Artikel", "https://img.example/a.jpg", "reading")]


def test_spread_creators_keeps_one_channel_from_filling_the_screen() -> None:
    items = [{"id": n, "creator": "A"} for n in range(4)] + [{"id": 10 + n, "creator": f"B{n}"} for n in range(3)]
    order = [i["creator"] for i in spread_creators(items)]
    assert order[:4] == ["A", "B0", "B1", "A"] or order[:3] == ["A", "B0", "B1"]
    assert all(not (order[n] == order[n + 1] == "A") for n in range(4))  # no back-to-back while others wait


def test_library_states(client) -> None:
    engine = client.app.state.engine
    with engine.begin() as conn:
        watched = _item(conn, "Gesehen")
        _watch(conn, watched)
        _item(conn, "Vorschlag")
        _item(conn, "Eigenes Video", origin="user_added")
    get = lambda state: [i["title"] for i in client.get("/api/content", params={"lang": "de", "state": state}).json()["items"]]  # noqa: E731
    assert get("watched") == ["Gesehen"]
    assert set(get("mine")) == {"Gesehen", "Eigenes Video"}
    assert set(get("all")) == {"Gesehen", "Vorschlag", "Eigenes Video"}


def test_top_up_queues_a_background_search_only_when_low(client) -> None:
    engine = client.app.state.engine
    first = client.post("/api/discover/top-up", json={"lang": "de"}).json()
    assert first["queued"] is True and set(first["shelves"]) == {"watch", "read"}
    again = client.post("/api/discover/top-up", json={"lang": "de"}).json()
    assert again["queued"] is False and again["reason"] == "already searching"
    with engine.begin() as conn:
        conn.execute(text("UPDATE jobs SET status = 'done' WHERE kind = 'update_content'"))
    assert client.post("/api/discover/top-up", json={"lang": "de"}).json()["reason"] == "searched recently"
    assert client.post("/api/discover/top-up", json={"lang": "de", "force": True}).json()["queued"] is True
    with engine.begin() as conn:
        conn.execute(text("UPDATE jobs SET status = 'done' WHERE kind = 'update_content'"))
        for n in range(topup.POOL_TARGET["watch"]):
            _item(conn, f"V{n}", creator=f"K{n}")
        for n in range(topup.POOL_TARGET["read"]):
            _item(conn, f"A{n}", kind="article")
        conn.execute(text("DELETE FROM app_settings WHERE key LIKE 'discover.auto_last.%'"))
    pool = client.get("/api/discover/pool", params={"lang": "de"}).json()
    assert pool["low"] == [] and pool["pools"] == {"watch": 24, "read": 12}
    assert client.post("/api/discover/top-up", json={"lang": "de"}).json()["reason"] == "enough suggestions"
    client.put("/api/discover/auto", json={"enabled": False})
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM content_items WHERE title LIKE 'A%'"))
    assert client.post("/api/discover/top-up", json={"lang": "de"}).json()["reason"] == "automatic search is off"


def test_feed_titles_lose_furigana() -> None:
    assert clean_title("JR&lt;ruby&gt;渋谷駅&lt;rt&gt;しぶやえき&lt;/rt&gt;&lt;/ruby&gt;のホーム") == "JR渋谷駅のホーム"
    rss = "<rss><channel><item><title>&lt;ruby&gt;駅&lt;rt&gt;えき&lt;/rt&gt;&lt;/ruby&gt;</title><link>https://a.example/1</link></item></channel></rss>"
    assert parse_feed(rss)[0].title == "駅"


def test_articles_come_from_every_feed_in_turn_and_off_level_feeds_rest(client, cfg, monkeypatch) -> None:
    feeds_cfg = [{"name": "Leicht", "url": "https://leicht.example/rss"}, {"name": "Schwer", "url": "https://schwer.example/rss"}]
    monkeypatch.setattr(
        discover, "load_sources",
        lambda cfg: {"defaults": {**discover.DEFAULTS, "articles_per_run": 4, "per_feed": 3, "keep_bands": ["i_plus_1", "too_easy", "comfortable"]},
                     "languages": {"de": {"feeds": feeds_cfg}}},
    )
    counter = {"n": 0}

    def entries(url: str) -> list[FeedEntry]:
        counter["n"] += 1
        host = url.split("/")[2]
        return [FeedEntry(f"{host} {counter['n']}-{k}", f"https://{host}/{counter['n']}/{k}", None) for k in range(5)]

    def article(url: str) -> Document:
        easy = "leicht" in url
        words = "Die Kinder spielen im Park." if easy else "Die Haushaltskonsolidierungsdebatte eskalierte unerwartet."
        return Document(url, None, "de", [Section(None, [words])], image="https://img.example/x.jpg")

    fetchers = discover.Fetchers(feed=entries, article=article, pause=lambda s: None)
    engine = client.app.state.engine
    stats = discover.discover_language(engine, cfg, "de", fetchers=fetchers, videos=False)
    assert stats["checked"] == 0  # no YouTube at all when only articles are wanted
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT source_url, metadata_json FROM content_items WHERE type = 'article'")).all()
        history = discover.feed_stats(conn, "de")
    hosts = [r[0].split("/")[2] for r in rows]
    assert hosts.count("leicht.example") == 2 and hosts.count("schwer.example") == 2  # round robin, not one feed first
    assert all('"site"' in r[1] and "img.example" in r[1] for r in rows)
    assert {url: v["tried"] for url, v in history.items()} == {f["url"]: 2 for f in feeds_cfg}


def test_tutor_topics_are_the_last_ten_things_watched_or_read(client) -> None:
    engine = client.app.state.engine
    with engine.begin() as conn:
        for n in range(12):
            item_id = _item(conn, f"Folge {n:02d}")
            conn.execute(
                text(
                    "INSERT INTO activity_sessions (language_code, activity, modality, tracking, started_at, active_seconds, "
                    "content_item_id) VALUES ('de', 'video', 'listening', 'auto', :t, 600, :i)"
                ),
                {"t": f"2026-11-{n + 1:02d}T10:00:00.000Z", "i": item_id},
            )
        _item(conn, "Nie geöffnet")
        article = _item(conn, "Gelesener Artikel", kind="article")
        conn.execute(text("UPDATE content_items SET last_opened_at = '2026-11-20T09:00:00.000Z' WHERE id = :i"), {"i": article})
    topics = client.get("/api/tutor/recent-items", params={"lang": "de"}).json()
    assert len(topics) == 10
    assert topics[0]["title"] == "Gelesener Artikel" and topics[0]["kind"] == "reading"
    assert topics[1]["title"] == "Folge 11" and "Nie geöffnet" not in [t["title"] for t in topics]
