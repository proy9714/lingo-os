"""update-content (ARCHITECTURE §7): find new videos and articles near your level, analyse them, keep the good ones.

Sources: YouTube channels listed for your language on the Comprehensible Input Wiki, YouTube searches built from
config/sources.yaml, and RSS feeds of articles. Every candidate is analysed against your profile; only those in or
near the i+1 band stay (status 'candidate', so they show up in Up Next and on the shelves). Network work happens
outside database transactions, requests are paced, and the run stops early if YouTube starts refusing.

Speed without less depth: videos and articles are looked for at the same time (different sites); a few YouTube
requests run side by side with their starts spaced (services/pacing.py); feeds and articles download in parallel;
your AI provider writes its searches while the channels are being listed. What gets checked, and how, is unchanged.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import Connection, Engine, text

from app.config import AppConfig
from app.db import settings_store
from app.engine.profile import get_profile
from app.ingest import ci_wiki, documents, feeds, youtube
from app.services import catalog, content, reading
from app.services.pacing import Pacer, Stopped, fan_out, writing
from app.timeutil import from_iso, to_iso, utc_now

STOP_AFTER_FAILURES = 3
WIKI_EVERY = timedelta(days=7)
DEFAULTS = {
    "youtube_parallel": 3,
    "per_run": 12, "articles_per_run": 30, "per_feed": 12, "min_minutes": 3, "max_minutes": 45, "prune_days": 30,
    "keep_bands": ["stretch", "i_plus_1", "comfortable"],
}
# A feed whose articles keep landing off your level is read less: after this many tries with a keep rate under
# FEED_MIN_RATE it is skipped, except every FEED_RETRY_EVERY runs (your level moves, so it gets another chance).
FEED_TRIES, FEED_MIN_RATE, FEED_RETRY_EVERY = 6, 0.15, 5
ARCHIVE_MIN_RATE = 0.4  # feeds at least this good get their older pages read too
FEED_WORKERS = 6  # feeds are on different sites: read them side by side
ARTICLE_WORKERS, ARTICLE_GAP = 4, 0.3  # articles download a few at a time, starts spaced
Progress = Callable[[float, str], None]


@dataclass
class Fetchers:
    """Everything that touches the network, replaceable in tests."""

    search: Callable[[str, int], list[youtube.Listing]] = youtube.search
    channel_uploads: Callable[[str, int, int], list[youtube.Listing]] = youtube.channel_uploads
    info: Callable[[str], youtube.VideoInfo] = youtube.fetch_info
    captions: Callable[[str, str], youtube.Captions | None] = field(
        default=lambda video_id, lang: youtube.fetch_captions(video_id, lang, strict=True)
    )
    feed: Callable[[str], list[feeds.FeedEntry]] = feeds.fetch_feed
    article: Callable[[str], documents.Document] = documents.fetch_article
    wiki: Callable[[str], str] = ci_wiki.fetch_page
    pause: Callable[[float], None] = time.sleep
    parallel: int = 3  # YouTube requests at once (sources.yaml defaults.youtube_parallel); 1 = one at a time


def load_sources(cfg: AppConfig) -> dict[str, Any]:
    path = cfg.root / "config" / "sources.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    raw = raw or {}
    return {"defaults": {**DEFAULTS, **(raw.get("defaults") or {})}, "languages": raw.get("languages") or {}}


# ------------------------------------------------------------------ CI Wiki


def sync_wiki(engine: Engine, cfg: AppConfig, lang: str, fetchers: Fetchers | None = None) -> dict[str, Any]:
    """Refresh this language's sources from the wiki page: at most once a week (its robots.txt allows the page)."""
    fetchers = fetchers or Fetchers()
    key = f"ci_wiki.synced.{lang}"
    with engine.connect() as conn:
        last = settings_store.get(conn, key)
    if last and utc_now() - from_iso(last) < WIKI_EVERY:
        return {"language": lang, "skipped": f"synced on {last[:10]}; the wiki is read at most once a week"}
    html = fetchers.wiki(lang)
    cache = cfg.data_dir / "cache" / "ci_wiki"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / f"{lang}.html").write_text(html, encoding="utf-8")
    resources = ci_wiki.parse_page(html)
    added = 0
    with writing(engine) as conn:
        for r in resources:
            kind, target = ("youtube_channel", r.youtube_url) if r.youtube_url else (r.kind, r.url)
            config = {"section": r.section, "note": r.note, "flags": r.flags, "site": r.url, "youtube": r.youtube_url}
            exists = conn.execute(
                text("SELECT 1 FROM content_sources WHERE kind = :k AND target = :t"), {"k": kind, "t": target}
            ).first()
            conn.execute(
                text(
                    "INSERT INTO content_sources (language_code, kind, name, target, origin, level_label, enabled, "
                    "fetch_every_hours, config_json) VALUES (:l, :k, :n, :t, 'ci_wiki', :lvl, :en, 168, :cfg) "
                    "ON CONFLICT(kind, target) DO UPDATE SET name = excluded.name, level_label = excluded.level_label, "
                    "config_json = excluded.config_json"
                ),
                {
                    "l": lang, "k": kind, "n": r.name[:200], "t": target, "lvl": r.level_label,
                    "en": int(kind == "youtube_channel"), "cfg": json.dumps(config, ensure_ascii=False),
                },
            )
            added += 0 if exists else 1
        settings_store.put(conn, key, to_iso(utc_now()))
    return {
        "language": lang,
        "resources": len(resources),
        "added": added,
        "youtube_channels": sum(1 for r in resources if r.youtube_url),
    }


def list_sources(conn: Connection, lang: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            "SELECT id, kind, name, target, origin, level_label, enabled, last_fetched_at, last_status, config_json "
            "FROM content_sources WHERE language_code = :l ORDER BY enabled DESC, name"
        ),
        {"l": lang},
    ).all()
    keys = ("id", "kind", "name", "target", "origin", "level_label", "enabled", "last_fetched_at", "last_status", "config")
    out = []
    for r in rows:
        row = dict(zip(keys, r))
        row["config"] = json.loads(row["config"] or "{}")
        row["enabled"] = bool(row["enabled"])
        out.append(row)
    return out


def set_source_enabled(conn: Connection, source_id: int, enabled: bool) -> None:
    conn.execute(text("UPDATE content_sources SET enabled = :e WHERE id = :i"), {"e": int(enabled), "i": source_id})


# ------------------------------------------------------------------ discovery


def _level(conn: Connection, lang: str) -> str:
    profile = get_profile(conn, lang) or {}
    if lang == "ja" and profile.get("level_alt"):
        return str(profile["level_alt"])
    return str(profile.get("level") or "B1")


# kept for callers and tests that used the old names
_known_ids = catalog.known_ids
_title_key = catalog.title_key
watched_titles = catalog.watched_titles


def _band(conn: Connection, item_id: int) -> str | None:
    return conn.execute(text("SELECT band FROM content_scores WHERE content_item_id = :i"), {"i": item_id}).scalar()


def _queries(spec: dict[str, Any], level: str, run_number: int, count: int = 3) -> list[str]:
    templates = spec.get("searches") or []
    topics = spec.get("topics") or [""]
    out = []
    for n in range(count):
        if not templates:
            break
        template = templates[(run_number + n) % len(templates)]
        topic = topics[(run_number * 3 + n) % len(topics)]
        out.append(" ".join(template.format(level=level, topic=topic).split()))
    return out


AI_QUERIES = 4


def ai_queries(engine: Engine, cfg: AppConfig, lang: str, level: str) -> list[str]:
    """Searches written by the AI provider you chose, from what you enjoy and your level: once a day per language.
    Empty when AI is off, so discovery carries on with the template searches."""
    from pydantic import BaseModel

    from app.ai.config import load_ai_config
    from app.ai.gateway import AIUnavailable, Gateway
    from app.db import settings_store
    from app.services import taste
    from app.services.explain import _language_name

    class Queries(BaseModel):
        queries: list[str]

    today = utc_now().strftime("%Y-%m-%d")
    key = f"discover.ai_queries.{lang}"
    with engine.connect() as conn:
        cached = settings_store.get(conn, key) or {}
        if cached.get("day") == today:
            return list(cached.get("queries") or [])
        profile = taste.profile(conn, lang)
        language = _language_name(conn, lang)
    summary = profile.summary()
    variables = {
        "language": language, "level": level or "beginner", "count": AI_QUERIES,
        "topics": ", ".join(summary["topics"][:12]) or "everyday life",
        "channels": ", ".join(c["name"] for c in summary["channels"][:5]) or "none yet",
    }
    try:
        result, _meta = Gateway(load_ai_config(cfg.root), engine).structured("content.query_gen", "query_gen", variables, Queries)
        queries = [" ".join(q.split())[:80] for q in result.queries if q.strip()][:AI_QUERIES]
    except (AIUnavailable, Exception):  # noqa: BLE001 - AI is a nicety here: discovery works without it
        queries = []
    with writing(engine) as conn:
        settings_store.put(conn, key, {"day": today, "queries": queries})
    return queries


class _Progress:
    """One progress bar for videos and articles found at the same time: each half reports 0..1 of its own work."""

    def __init__(self, say: Progress, weights: dict[str, float]) -> None:
        total = sum(weights.values()) or 1.0
        self.say, self.weights = say, {k: v / total for k, v in weights.items()}
        self.done = {k: 0.0 for k in weights}
        self.lock = threading.Lock()

    def part(self, name: str, lo: float = 0.0, hi: float = 1.0) -> Progress:
        """A progress callback for one half, mapping its own [lo, hi] range onto its share of the bar."""

        def report(fraction: float, message: str) -> None:
            share = (fraction - lo) / (hi - lo) if hi > lo else 1.0
            with self.lock:
                self.done[name] = max(self.done[name], min(1.0, max(0.0, share)))
                overall = 0.02 + 0.95 * sum(self.weights[k] * v for k, v in self.done.items())
                self.say(overall, message)

        return report


def discover_language(
    engine: Engine,
    cfg: AppConfig,
    lang: str,
    *,
    per_run: int | None = None,
    dry_run: bool = False,
    fetchers: Fetchers | None = None,
    progress: Progress | None = None,
    videos: bool = True,
    articles: bool = True,
) -> dict[str, Any]:
    """Look for new videos (`videos`) and articles (`articles`) for one language, both at once."""
    use_ai = fetchers is None and not dry_run  # tests and dry runs pass their own fetchers: never call a real AI
    sources = load_sources(cfg)
    settings, spec = sources["defaults"], sources["languages"].get(lang, {})
    if fetchers is None:
        fetchers = Fetchers(parallel=max(1, int(settings.get("youtube_parallel", 3) or 1)))
    limit = (per_run or int(settings["per_run"])) if videos else 0
    stats: dict[str, Any] = {"language": lang, "listed": 0, "checked": 0, "added": 0, "catalogued": 0, "off_level": 0,
                             "no_captions": 0, "articles_added": 0, "errors": [], "stopped_early": False, "added_titles": [],
                             "channels_added": []}
    say = progress or (lambda fraction, message: None)
    started = time.monotonic()

    with writing(engine) as conn:
        level = _level(conn, lang)
        run_number = conn.execute(text("SELECT COUNT(*) FROM scrape_runs WHERE language_code = :l"), {"l": lang}).scalar() or 0
        youtube_ok = videos and not catalog.youtube_refused_recently(conn)
        run_id = None
        if not dry_run:
            # a run cut off by closing the app never finished: close it so it doesn't look busy forever
            conn.execute(
                text("UPDATE scrape_runs SET status = 'failed', finished_at = :t WHERE language_code = :l AND status = 'running'"),
                {"l": lang, "t": to_iso(utc_now())},
            )
            run_id = conn.execute(
                text("INSERT INTO scrape_runs (language_code, status) VALUES (:l, 'running')"), {"l": lang}
            ).lastrowid
    if videos and not youtube_ok:
        stats["stopped_early"] = True
        stats["errors"].append("YouTube refused recently; videos are skipped for now")

    bar = _Progress(say, {"videos": 0.7 if youtube_ok else 0.0, "articles": 0.3 if articles else 0.0})
    # Articles come from other sites than YouTube: they're looked for at the same time as the videos.
    article_stats: dict[str, Any] = {"articles_added": 0, "off_level": 0, "errors": [], "added_titles": []}
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="discover") as background:
        articles_done = (
            background.submit(
                _discover_articles, engine, cfg, lang, spec, settings, article_stats, fetchers,
                bar.part("articles", 0.05, 0.97), run_number, dry_run, 0.05,
            )
            if articles
            else None
        )
        try:
            if youtube_ok and dry_run:
                _plan_videos(engine, lang, spec, level, run_number, limit, fetchers, stats)
            elif youtube_ok:
                _discover_videos(
                    engine, cfg, lang, spec, settings, stats, fetchers, bar.part("videos", 0.0, 0.97),
                    level, run_number, limit, use_ai, background,
                )
        finally:
            if articles_done is not None:
                articles_done.result()  # waits for the articles half; its error, if any, surfaces here
    for key in ("articles_added", "off_level"):
        stats[key] += article_stats[key]
    stats["errors"] += article_stats["errors"]
    stats["added_titles"] += article_stats["added_titles"]
    if "would_read" in article_stats:
        stats["would_read"] = article_stats["would_read"]
    stats["seconds"] = round(time.monotonic() - started, 1)

    if not dry_run:
        with writing(engine) as conn:
            stats["pruned"] = prune(conn, int(settings["prune_days"]), lang)
            conn.execute(
                text(
                    "UPDATE scrape_runs SET status = :s, candidates_found = :f, candidates_added = :a, stats_json = :j, "
                    "finished_at = :t WHERE id = :id"
                ),
                {
                    "s": "partial" if stats["stopped_early"] or stats["errors"] else "done", "f": stats["listed"],
                    "a": stats["added"] + stats["articles_added"], "j": json.dumps(stats, ensure_ascii=False),
                    "t": to_iso(utc_now()), "id": run_id,
                },
            )
    return stats


def _plan_videos(
    engine: Engine, lang: str, spec: dict[str, Any], level: str, run_number: int, limit: int, fetchers: Fetchers,
    stats: dict[str, Any],
) -> None:
    """A dry run: what the searches would list and check, without storing anything."""
    with engine.connect() as conn:
        channels = catalog.channel_sources(conn, lang)
    listings: list[tuple[youtube.Listing, str]] = []
    for query in _queries(spec, level, run_number):
        listings += [(item, f"search: {query}") for item in fetchers.search(query, 20)]
    with engine.connect() as conn:
        known = catalog.known_ids(conn, "youtube", [v.video_id for v, _ in listings])
        seen_titles = catalog.watched_titles(conn, lang)
    unique = {v.video_id: (v, via) for v, via in reversed(listings)}  # first listing of each video wins
    fresh = [(v, via) for v, via in unique.values() if v.video_id not in known and catalog.title_key(v.title) not in seen_titles]
    stats["listed"] = len(fresh)
    stats["would_list_channels"] = [c["name"] for c in channels[: catalog.CHANNELS_PER_RUN]]
    stats["would_check"] = [{"video_id": v.video_id, "title": v.title, "channel": v.channel, "via": via} for v, via in fresh[:limit]]


def _discover_videos(
    engine: Engine,
    cfg: AppConfig,
    lang: str,
    spec: dict[str, Any],
    settings: dict[str, Any],
    stats: dict[str, Any],
    fetchers: Fetchers,
    say: Progress,
    level: str,
    run_number: int,
    limit: int,
    use_ai: bool,
    background: ThreadPoolExecutor,
) -> None:
    """Channels you watch, their uploads, searches at your level, then measure the most promising videos."""
    from app.services import taste

    # your AI provider writes its searches while the channels are being listed
    written = background.submit(ai_queries, engine, cfg, lang, level) if use_ai else None
    with engine.connect() as conn:
        profile = taste.profile(conn, lang)
    # 1. Channels: the ones you watch, then list many uploads from each (cheap: no per-video request).
    say(0.02, "finding channels you watch")
    stats["channels_added"] = catalog.resolve_history_channels(engine, lang, fetchers)
    listed = catalog.list_channels(
        engine, settings, lang, fetchers, affinity=profile.channel_affinity, say=say, span=(0.05, 0.35)
    )
    stats["seen"] = listed["listed"]
    stats["catalogued"] += listed["new"]
    stats["errors"] += listed["errors"]
    refused = listed["refused"]
    # 2. Searches at your level: new channels come from here.
    if not refused:
        # two template searches, then up to two written by your AI provider from what you enjoy
        searches = _queries(spec, level, run_number, count=2 if use_ai else 3)
        if written is not None:
            say(0.37, "using your AI provider's searches")
            try:
                ai = written.result()
            except Exception:  # noqa: BLE001 - the template searches are enough without it
                ai = []
            searches += [q for q in ai[run_number % 2 :: 2][:2] if q not in searches] or _queries(spec, level, run_number + 7, 1)
        listings: list[tuple[youtube.Listing, str]] = []
        say(0.38, f"searching YouTube ({len(searches)} searches)")
        for query, found, error in fan_out(
            searches, lambda q: fetchers.search(q, 20), workers=max(1, fetchers.parallel),
            pacer=catalog.youtube_pacer(fetchers), name="yt-search",
        ):
            if isinstance(error, Stopped):
                continue
            if isinstance(error, youtube.YouTubeError):
                stats["errors"].append(f"search '{query}': {error}"[:200])
                if catalog._is_refusal(error):
                    refused = True
                    break
                continue
            if error is not None:
                raise error
            listings += [(item, f"search: {query}") for item in found or []]
            if fetchers.parallel <= 1:
                fetchers.pause(catalog.PAUSE)
        stats["seen"] += len(listings)
        stats["catalogued"] += catalog.add_listings(engine, lang, listings, settings)
    # 3. Estimate every new video's level, then measure the most promising ones.
    with writing(engine) as conn:
        stats["estimated"] = catalog.estimate_scores(conn, lang)
    if not refused:
        measured = catalog.verify(
            engine, lang, fetchers, settings["keep_bands"], limit=limit, say=say, span=(0.42, 0.97),
        )
        stats["checked"] += measured["checked"]
        stats["added"] += measured["kept"]
        stats["no_captions"] += measured["no_captions"]
        stats["off_level"] += measured["off_level"]
        stats["errors"] += measured["errors"]
        stats["added_titles"] += measured["kept_titles"]
        refused = measured["refused"]
    stats["stopped_early"] = refused
    stats["listed"] = stats["catalogued"]  # new videos in the catalogue


# ------------------------------------------------------------------ articles


def feed_stats(conn: Connection, lang: str) -> dict[str, dict[str, int]]:
    """Per feed: how many of its articles were read and how many were near your level."""
    return settings_store.get(conn, f"feed_stats.{lang}", {}) or {}


def _paged(url: str, page: int) -> str:
    """An older page of a feed (WordPress and many others accept ?paged=N)."""
    return f"{url}{'&' if '?' in url else '?'}paged={page}"


def _keep_rate(entry: dict[str, int]) -> float:
    return (entry.get("kept", 0) + 1) / (entry.get("tried", 0) + 2)


def _discover_articles(
    engine: Engine,
    cfg: AppConfig,
    lang: str,
    spec: dict[str, Any],
    settings: dict[str, Any],
    stats: dict[str, Any],
    fetchers: Fetchers,
    say: Progress,
    run_number: int,
    dry_run: bool,
    start: float,
) -> None:
    configured = [f for f in spec.get("feeds") or [] if f.get("url")]
    with engine.connect() as conn:
        history = feed_stats(conn, lang)

    def worth_reading(feed: dict[str, Any]) -> bool:
        entry = history.get(feed["url"], {})
        return entry.get("tried", 0) < FEED_TRIES or _keep_rate(entry) >= FEED_MIN_RATE or run_number % FEED_RETRY_EVERY == 0

    ordered = sorted((f for f in configured if worth_reading(f)), key=lambda f: -_keep_rate(history.get(f["url"], {})))
    weights = {f["url"]: _keep_rate(history.get(f["url"], {})) for f in ordered}
    total_weight = sum(weights.values()) or 1.0
    budget = int(settings["articles_per_run"])
    per_feed = int(settings["per_feed"])
    queues: list[tuple[dict[str, Any], list[feeds.FeedEntry]]] = []
    for name in ordered:  # every feed's tally exists before the feeds are read side by side
        history.setdefault(name["url"], {"tried": 0, "kept": 0})

    def read_feed(feed: dict[str, Any]) -> list[feeds.FeedEntry]:
        """A feed's new entries, with older pages of it when it suits you and has run dry."""
        url = feed["url"]
        quota = min(per_feed, max(2, round(budget * weights[url] / total_weight)))
        entries = fetchers.feed(url)
        with engine.connect() as conn:
            known = _known_ids(conn, "web", [e.url for e in entries])
        fresh = [e for e in entries if e.url not in known]
        # A feed that suits you and has run dry gets its archive read, a page further back each run.
        tally = history[url]
        pages = 0
        while len(fresh) < quota and tally.get("archive", True) and weights[url] >= ARCHIVE_MIN_RATE and pages < 2 and not dry_run:
            page = int(tally.get("page", 2))
            try:
                older = fetchers.feed(_paged(url, page))
            except feeds.FeedError:
                older = []
            with engine.connect() as conn:
                known_older = _known_ids(conn, "web", [e.url for e in older])
            new_older = [e for e in older if e.url not in known_older and e.url not in {f.url for f in fresh}]
            if not older or {e.url for e in older} <= {e.url for e in entries}:
                tally["archive"] = False  # no archive pages on this feed
                break
            tally["page"] = page + 1
            fresh += new_older
            pages += 1
        return fresh[:quota]

    say(start, f"reading {len(ordered)} feeds")
    for feed, fresh, error in fan_out(ordered, read_feed, workers=FEED_WORKERS, name="feeds"):
        if isinstance(error, feeds.FeedError):
            stats["errors"].append(f"{feed.get('name', feed['url'])}: {error}"[:200])
            continue
        if error is not None:
            raise error
        if fresh:
            queues.append((feed, fresh))
    with writing(engine) as conn:
        settings_store.put(conn, f"feed_stats.{lang}", history)
    plan: list[tuple[dict[str, Any], feeds.FeedEntry]] = []
    while budget > 0 and any(entries for _, entries in queues):
        for feed, entries in queues:
            if entries and budget > 0:
                plan.append((feed, entries.pop(0)))
                budget -= 1

    if dry_run:
        for feed, entry in plan:
            stats.setdefault("would_read", []).append({"title": entry.title, "url": entry.url, "feed": feed.get("name") or feed["url"]})
        return
    # articles download a few at a time; each is analysed and stored as it arrives, in plan order
    downloads = fan_out(
        plan, lambda pair: fetchers.article(pair[1].url), workers=ARTICLE_WORKERS, pacer=Pacer(ARTICLE_GAP, fetchers.pause),
        name="articles",
    )
    for number, ((feed, entry), doc, error) in enumerate(downloads):
        name = feed.get("name") or feed["url"]
        say(start + (0.97 - start) * (number + 1) / len(plan), f"reading article {number + 1} of {len(plan)}: {entry.title[:60]}")
        if isinstance(error, documents.DocumentError):
            stats["errors"].append(f"{entry.url}: {error}"[:200])
            continue
        if error is not None:
            raise error
        with writing(engine) as conn:
            item_id, _ = reading.import_document(conn, cfg, lang, doc, item_type="article", source="web", source_url=entry.url)
            keep = _band(conn, item_id) in settings["keep_bands"]
            conn.execute(
                text("UPDATE content_items SET origin = 'scraper', status = :s, creator = COALESCE(creator, :c) WHERE id = :i"),
                {"s": "candidate", "c": name, "i": item_id},  # off-level too: it fills the list while little fits
            )
            content.set_metadata(
                conn, item_id, discovered_via=f"feed: {name}", discovery="ok" if keep else "off_level", site=name
            )
            tally = history.setdefault(feed["url"], {"tried": 0, "kept": 0})
            tally["tried"] += 1
            tally["kept"] += int(keep)
            settings_store.put(conn, f"feed_stats.{lang}", history)
        if keep:
            stats["articles_added"] += 1
            stats["added_titles"].append(doc.title)
        else:
            stats["off_level"] += 1


def prune(conn: Connection, days: int, lang: str | None = None) -> int:
    """Remove discovered items nobody opened, older than `days`: dropped ones (so they can be re-checked as your level
    moves) and measured candidates. Measured candidates that fit your level are what suggestions are made of: they
    stay four times as long. Estimated catalogue entries stay; things you dismissed yourself, added or watched are
    never removed."""
    result = conn.execute(
        text(
            "DELETE FROM content_items WHERE origin = 'scraper' AND status IN ('candidate', 'dismissed') "
            "AND analysis_status = 'done' AND last_opened_at IS NULL AND (:l IS NULL OR language_code = :l) "
            "AND COALESCE(json_extract(metadata_json, '$.dismissed_by_you'), 0) = 0 "
            "AND json_extract(metadata_json, '$.saved_at') IS NULL "
            "AND added_at < strftime('%Y-%m-%dT%H:%M:%fZ', 'now', :age) "
            "AND (status = 'dismissed' OR added_at < strftime('%Y-%m-%dT%H:%M:%fZ', 'now', :keep) OR NOT EXISTS ("
            " SELECT 1 FROM content_scores cs WHERE cs.content_item_id = content_items.id AND cs.estimated = 0 "
            " AND cs.band IN ('stretch', 'i_plus_1', 'comfortable'))) "
            "AND NOT EXISTS (SELECT 1 FROM activity_sessions s WHERE s.content_item_id = content_items.id)"
        ),
        {"l": lang, "age": f"-{days} days", "keep": f"-{days * 4} days"},
    )
    return result.rowcount or 0


def update_content(
    engine: Engine,
    cfg: AppConfig,
    lang: str | None = None,
    *,
    per_run: int | None = None,
    dry_run: bool = False,
    fetchers: Fetchers | None = None,
    progress: Progress | None = None,
    videos: bool = True,
    articles: bool = True,
) -> dict[str, Any]:
    results = {}
    codes = [code for code in cfg.language_codes if lang in (None, code)]
    for number, code in enumerate(codes):
        wiki = None
        if not dry_run and videos:
            try:
                wiki = sync_wiki(engine, cfg, code, fetchers)
            except ci_wiki.WikiError as exc:
                wiki = {"error": str(exc)}

        def scaled(fraction: float, message: str, number: int = number, code: str = code) -> None:
            if progress:
                prefix = f"{code.upper()}: " if len(codes) > 1 else ""
                progress((number + fraction) / len(codes), prefix + message)

        results[code] = {
            "wiki": wiki,
            **discover_language(
                engine, cfg, code, per_run=per_run, dry_run=dry_run, fetchers=fetchers, progress=scaled,
                videos=videos, articles=articles,
            ),
        }
    return results


def recent_runs(conn: Connection, limit: int = 6) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            "SELECT id, language_code, status, candidates_found, candidates_added, stats_json, started_at, finished_at "
            "FROM scrape_runs ORDER BY id DESC LIMIT :n"
        ),
        {"n": limit},
    ).all()
    out = []
    for r in rows:
        stats = json.loads(r[5] or "{}")
        out.append(
            {
                "id": r[0], "language": r[1], "status": r[2], "listed": r[3], "added": r[4], "started_at": r[6],
                "finished_at": r[7], "errors": stats.get("errors", [])[:5], "added_titles": stats.get("added_titles", [])[:12],
                "stopped_early": stats.get("stopped_early", False),
            }
        )
    return out


def cache_dir(cfg: AppConfig) -> Path:
    return cfg.data_dir / "cache"
