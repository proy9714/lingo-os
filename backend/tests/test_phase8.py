from __future__ import annotations

import json
from datetime import timedelta

import pytest
from sqlalchemy import text

from app.ingest import ci_wiki, youtube
from app.ingest.documents import Document, Section
from app.ingest.feeds import FeedEntry, parse_feed
from app.ingest.subtitles import Cue
from app.services import discover
from app.services.evolve import Proposal, evolve, validate
from app.timeutil import local_today

WIKI = """
<html><body><div id="mw-content-text">
<h2><span>Comprehensible Input Resources</span></h2><h3>Video</h3>
<p><a class="external text" href="https://www.youtube.com/@KanalEins">Kanal Eins</a> (Beginner stories.)
<img src="https://x/Video_camera_icon_svg.svg"/> <img src="//x/Caption_icon_abc.svg"/></p>
<ul><li><a class="external text" href="https://example.com/app">Paid App</a> <img src="//x/Money_icon.svg"/>
  <ul><li>Free videos on <a class="external text" href="https://www.youtube.com/@PaidAppFree">YouTube</a></li></ul></li></ul>
<h3>Reading</h3>
<p><a class="external text" href="https://reader.example/">Leseecke</a> (A2-B1 graded readers) <img src="//x/Book_(21025).svg"/></p>
<h2>Navigation</h2><p><a class="external text" href="https://nav.example/">Not a resource</a></p>
</div></body></html>
"""

CUES = [Cue(0, 2000, "Ich gehe heute in den Park."), Cue(2000, 4000, "Dort spielen die Kinder."), Cue(4000, 6000, "Das Wetter ist schön.")]


def test_wiki_page_parsing() -> None:
    resources = ci_wiki.parse_page(WIKI)
    assert [r.name for r in resources] == ["Kanal Eins", "Paid App", "Leseecke"]
    kanal, paid, reader = resources
    assert kanal.kind == "youtube_channel" and kanal.flags == ["video", "captions"] and kanal.level_label == "Beginner"
    assert kanal.section == "Comprehensible Input Resources / Video"
    assert paid.youtube_url == "https://www.youtube.com/@PaidAppFree" and "paid" in paid.flags
    assert reader.kind == "web_section" and reader.level_label == "A2-B1"


def test_sync_wiki_is_weekly_and_only_youtube_is_fetched(client, cfg) -> None:
    fetchers = discover.Fetchers(wiki=lambda lang: WIKI)
    engine = client.app.state.engine
    first = discover.sync_wiki(engine, cfg, "de", fetchers)
    assert first["resources"] == 3 and first["youtube_channels"] == 2
    assert "skipped" in discover.sync_wiki(engine, cfg, "de", fetchers)
    sources = client.get("/api/sources", params={"lang": "de"}).json()
    fetched = {s["name"]: s["enabled"] for s in sources}
    assert fetched == {"Kanal Eins": True, "Paid App": True, "Leseecke": False}
    paid = next(s for s in sources if s["name"] == "Paid App")
    assert paid["target"] == "https://www.youtube.com/@PaidAppFree"  # only its free YouTube channel is ever fetched


def test_feeds_rss_and_atom() -> None:
    rss = "<rss><channel><item><title>Eins</title><link>https://a.example/1</link><pubDate>Mon</pubDate></item></channel></rss>"
    atom = '<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Zwei</title><link href="https://a.example/2"/></entry></feed>'
    assert [(e.title, e.url) for e in parse_feed(rss)] == [("Eins", "https://a.example/1")]
    assert [(e.title, e.url) for e in parse_feed(atom)] == [("Zwei", "https://a.example/2")]


def test_strict_captions_refuse_machine_translation() -> None:
    track = [{"ext": "json3", "url": "u"}]
    english = {"language": "en", "automatic_captions": {"en-orig": track, "de": track}}
    assert youtube.choose_track(english, "de") is not None  # history: fine
    assert youtube.choose_track(english, "de", strict=True) is None  # discovery: not German
    lesson = {"language": "en", "subtitles": {"es": track}}
    assert youtube.choose_track(lesson, "es", strict=True) is None  # translated subtitles of an English video
    german = {"language": "de", "automatic_captions": {"de-orig": track, "en": track}}
    assert youtube.choose_track(german, "de", strict=True)[1] == "de-orig"


@pytest.fixture
def fake_sources(monkeypatch):
    def load(cfg):
        return {
            "defaults": {**discover.DEFAULTS, "keep_bands": ["too_easy", "comfortable", "i_plus_1", "stretch", "too_hard"],
                         "articles_per_run": 1},
            "languages": {"de": {"searches": ["Deutsch {level} {topic}"], "topics": ["Alltag"],
                                 "feeds": [{"name": "Testfeed", "url": "https://feed.example/rss"}]}},
        }

    monkeypatch.setattr(discover, "load_sources", load)


def test_discovery_keeps_candidates_and_skips_known(client, cfg, fake_sources) -> None:
    listings = [
        youtube.Listing("aaaaaaaaaaa", "Video A", "Kanal", 600),
        youtube.Listing("bbbbbbbbbbb", "Video B", "Kanal", 600),
        youtube.Listing("ccccccccccc", "Too short", "Kanal", 30),
    ]
    searched: list[str] = []
    fetchers = discover.Fetchers(
        search=lambda q, n: searched.append(q) or listings,
        channel_uploads=lambda url, n: [],
        captions=lambda vid, lang: None if vid == "bbbbbbbbbbb" else youtube.Captions("manual", "de", "vtt", CUES),
        feed=lambda url: [FeedEntry("Artikel", "https://news.example/1", None)],
        article=lambda url: Document("Artikel", None, "de", [Section("", ["Die Kinder spielen heute im Park."])]),
        wiki=lambda lang: WIKI,
        pause=lambda s: None,
    )
    engine = client.app.state.engine
    stats = discover.discover_language(engine, cfg, "de", fetchers=fetchers)
    assert searched and "Alltag" in searched[0]
    assert (stats["listed"], stats["checked"], stats["added"], stats["no_captions"], stats["articles_added"]) == (2, 2, 1, 1, 1)
    shelf = client.get("/api/content", params={"lang": "de"}).json()["items"]
    assert [(i["title"], i["status"]) for i in shelf] == [("Video A", "candidate")]
    picks = client.get("/api/recommend", params={"lang": "de"}).json()["picks"]
    assert {p["title"] for p in picks} == {"Video A", "Artikel"}

    again = discover.discover_language(engine, cfg, "de", fetchers=fetchers)
    assert again["listed"] == 0 and again["articles_added"] == 0  # nothing is checked twice
    with engine.connect() as conn:
        runs = conn.execute(text("SELECT status, candidates_added FROM scrape_runs ORDER BY id")).all()
    assert runs == [("done", 2), ("done", 0)]

    # unopened candidates age out; anything you opened stays
    with engine.begin() as conn:
        conn.execute(text("UPDATE content_items SET added_at = '2020-01-01T00:00:00.000Z' WHERE origin = 'scraper'"))
        conn.execute(text("UPDATE content_items SET last_opened_at = '2026-01-01T00:00:00.000Z' WHERE title = 'Artikel'"))
        assert discover.prune(conn, 30, "de") == 2
        left = conn.execute(text("SELECT title FROM content_items WHERE origin = 'scraper'")).scalars().all()
    assert left == ["Artikel"]


def test_discovery_skips_videos_you_already_watched(client, cfg, fake_sources) -> None:
    engine = client.app.state.engine
    with engine.begin() as conn:  # a tracker CSV row: watched, title only
        conn.execute(
            text(
                "INSERT INTO activity_sessions (language_code, activity, modality, tracking, started_at, active_seconds, title) "
                "VALUES ('de', 'video', 'listening', 'import', '2026-11-01T10:00:00.000Z', 600, 'Ein Tag in Berlin | Folge 3')"
            )
        )
    fetchers = discover.Fetchers(
        search=lambda q, n: [youtube.Listing("reupload000", "EIN TAG IN BERLIN – Folge 3", "Other", 600),
                             youtube.Listing("brandnew000", "Etwas ganz Neues", "K", 600)],
        channel_uploads=lambda url, n: [], captions=lambda vid, lang: None, feed=lambda url: [], wiki=lambda lang: WIKI,
        pause=lambda s: None,
    )
    stats = discover.discover_language(engine, cfg, "de", fetchers=fetchers, dry_run=True)
    assert [w["video_id"] for w in stats["would_check"]] == ["brandnew000"]


def test_discovery_stops_when_youtube_refuses(client, cfg, fake_sources) -> None:
    def refuse(vid, lang):
        raise youtube.YouTubeError("Sign in to confirm you're not a bot")

    fetchers = discover.Fetchers(
        search=lambda q, n: [youtube.Listing(f"vid{i:08d}", f"V{i}", "K", 600) for i in range(6)],
        channel_uploads=lambda url, n: [], captions=refuse, feed=lambda url: [], wiki=lambda lang: WIKI, pause=lambda s: None,
    )
    stats = discover.discover_language(client.app.state.engine, cfg, "de", fetchers=fetchers)
    assert stats["stopped_early"] is True and stats["checked"] == 1


def _seed_week(engine) -> None:
    with engine.begin() as conn:
        for n, (progress, status) in enumerate([(0.1, "in_progress"), (0.15, "in_progress"), (1.0, "finished")]):
            item = conn.execute(
                text(
                    "INSERT INTO content_items (language_code, type, title, origin, source, external_id, status, progress, word_count) "
                    "VALUES ('de', 'text', :t, 'user_added', 'paste', :e, :s, :p, 2000)"
                ),
                {"t": f"Text {n}", "e": f"t{n}", "s": status, "p": progress},
            ).lastrowid
            conn.execute(
                text(
                    "INSERT INTO activity_sessions (language_code, activity, modality, tracking, started_at, ended_at, active_seconds, "
                    "content_item_id) VALUES ('de', 'reading', 'reading', 'auto', strftime('%Y-%m-%dT%H:%M:%fZ','now','-1 hours'), "
                    "strftime('%Y-%m-%dT%H:%M:%fZ','now'), 900, :i)"
                ),
                {"i": item},
            )
        lexeme = conn.execute(text("INSERT INTO lexemes (language_code, lemma, reading, pos) VALUES ('de', 'Kiste', '', 'NOUN')")).lastrowid
        conn.execute(text("INSERT INTO user_words (lexeme_id, status, p_known) VALUES (:x, 'learning', 0.3)"), {"x": lexeme})


def test_weekly_review_without_ai(client, cfg) -> None:
    engine = client.app.state.engine
    _seed_week(engine)
    result = evolve(engine, cfg, None, use_llm=False)
    de = result["languages"]["de"]
    assert de["minutes"] == 45.0
    assert de["adjustments"][0]["to"] == 0.01 and "dropped early" in de["adjustments"][0]["reason"]
    reports = client.get("/api/reports").json()
    assert reports[0]["path"] == result["markdown"] and reports[0]["minutes"] == 45
    markdown = client.get("/api/reports/file", params={"path": result["markdown"]}).text
    assert "45 minutes" in markdown and "a range" in markdown
    assert client.get("/api/reports/file", params={"path": "../lingo.db"}).status_code == 404
    with engine.connect() as conn:
        assert conn.execute(text("SELECT reason FROM profile_snapshots WHERE language_code = 'de' ORDER BY profile_version DESC LIMIT 1")).scalar() == "weekly_evolve"
    # the band moves at most two points a week and four in total
    for _ in range(6):
        evolve(engine, cfg, None, use_llm=False)
    with engine.connect() as conn:
        assert json.loads(conn.execute(text("SELECT value_json FROM app_settings WHERE key = 'band_shift.de'")).scalar()) == 0.04


def test_agent_proposal_goes_through_guardrails(client, cfg) -> None:
    engine = client.app.state.engine
    _seed_week(engine)
    proposal = {
        "narrative_md": "Good week.",
        "focus_words": ["Kiste", "Erfundenes"],
        "focus_grammar": ["Perfekt mit sein"],
        "tutor_instructions_md": "Talk about travel.",
        "style": {"speech_rate": 1.5, "max_sentence_words": 40},
        "suggested_goal_minutes": 45,
    }
    result = evolve(engine, cfg, None, proposals={"de": proposal})
    notes = " ".join(result["languages"]["de"]["notes"])
    assert "learning list" in notes and "speech rate" in notes
    brief = client.get("/api/tutor/options", params={"lang": "de"}).json()
    assert brief["speech_rate"] == 1.0  # 0.9 + at most 0.1
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT origin, instructions_md, style_json FROM tutor_instructions WHERE language_code = 'de' AND is_active = 1")
        ).first()
    assert row[0] == "evolve" and "Kiste" in row[1] and "Erfundenes" not in row[1] and "Perfekt mit sein" in row[1]


def test_validate_clamps_sentence_length() -> None:
    cleaned, notes = validate(
        Proposal(style={"max_sentence_words": 3}), {"learning_words": [], "style": {"max_sentence_words": 12}}
    )
    assert cleaned.style.max_sentence_words == 9 and notes


def test_jobs_can_be_queued(client) -> None:
    assert client.post("/api/discover/run", json={"lang": "de"}).status_code == 202
    assert client.post("/api/evolve/run", json={}).status_code == 202
    assert client.get("/api/discover/status").json()["job"]["kind"] == "update_content"


def test_window_covers_today() -> None:
    from app.services.evolve import _window

    start, end, first, last = _window(7)
    assert last == local_today() and (last - first) == timedelta(days=6) and start < end
