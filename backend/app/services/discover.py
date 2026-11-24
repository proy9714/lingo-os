"""update-content (ARCHITECTURE §7): find new videos and articles near your level, analyse them, keep the good ones.

Sources: YouTube channels listed for your language on the Comprehensible Input Wiki, YouTube searches built from
config/sources.yaml, and RSS feeds of articles. Every candidate is analysed against your profile; only those in or
near the i+1 band stay (status 'candidate', so they show up in Up Next and on the shelves). Network work happens
outside database transactions, requests are paced, and the run stops early if YouTube starts refusing.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
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
from app.timeutil import from_iso, to_iso, utc_now

PAUSE_SECONDS = 2.0
STOP_AFTER_FAILURES = 3
WIKI_EVERY = timedelta(days=7)
DEFAULTS = {
    "per_run": 12, "articles_per_run": 30, "per_feed": 12, "min_minutes": 3, "max_minutes": 45, "prune_days": 30,
    "keep_bands": ["stretch", "i_plus_1", "comfortable"],
}
# A feed whose articles keep landing off your level is read less: after this many tries with a keep rate under
# FEED_MIN_RATE it is skipped, except every FEED_RETRY_EVERY runs (your level moves, so it gets another chance).
FEED_TRIES, FEED_MIN_RATE, FEED_RETRY_EVERY = 6, 0.15, 5
ARCHIVE_MIN_RATE = 0.4  # feeds at least this good get their older pages read too
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
    with engine.begin() as conn:
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
    """Look for new videos (`videos`) and articles (`articles`) for one language."""
    from app.services import taste

    fetchers = fetchers or Fetchers()
    sources = load_sources(cfg)
    settings, spec = sources["defaults"], sources["languages"].get(lang, {})
    limit = (per_run or int(settings["per_run"])) if videos else 0
    stats: dict[str, Any] = {"language": lang, "listed": 0, "checked": 0, "added": 0, "catalogued": 0, "off_level": 0,
                             "no_captions": 0, "articles_added": 0, "errors": [], "stopped_early": False, "added_titles": [],
                             "channels_added": []}
    say = progress or (lambda fraction, message: None)

    with engine.begin() as conn:
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

    if youtube_ok and dry_run:
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
    elif youtube_ok:
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
            listings: list[tuple[youtube.Listing, str]] = []
            for query in _queries(spec, level, run_number):
                say(0.38, f"searching: {query[:50]}")
                try:
                    listings += [(item, f"search: {query}") for item in fetchers.search(query, 20)]
                except youtube.YouTubeError as exc:
                    stats["errors"].append(f"search '{query}': {exc}"[:200])
                    if catalog._is_refusal(exc):
                        refused = True
                        break
                fetchers.pause(catalog.PAUSE)
            stats["seen"] += len(listings)
            stats["catalogued"] += catalog.add_listings(engine, lang, listings, settings)
        # 3. Estimate every new video's level, then measure the most promising ones.
        with engine.begin() as conn:
            stats["estimated"] = catalog.estimate_scores(conn, lang)
        if not refused:
            measured = catalog.verify(
                engine, lang, fetchers, settings["keep_bands"], limit=limit, say=say,
                span=(0.42, 0.72 if articles else 0.97),
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

    # 4. Articles from the feeds: the feeds that suit your level get most of the budget.
    if articles:
        _discover_articles(
            engine, cfg, lang, spec, settings, stats, fetchers, say, run_number, dry_run, start=0.75 if videos else 0.05
        )

    if not dry_run:
        with engine.begin() as conn:
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
    for feed in ordered:
        url = feed["url"]
        quota = min(per_feed, max(2, round(budget * weights[url] / total_weight)))
        try:
            entries = fetchers.feed(url)
        except feeds.FeedError as exc:
            stats["errors"].append(f"{feed.get('name', url)}: {exc}"[:200])
            continue
        with engine.connect() as conn:
            known = _known_ids(conn, "web", [e.url for e in entries])
        fresh = [e for e in entries if e.url not in known]
        # A feed that suits you and has run dry gets its archive read, a page further back each run.
        tally = history.setdefault(url, {"tried": 0, "kept": 0})
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
            fetchers.pause(PAUSE_SECONDS / 4)
        if fresh:
            queues.append((feed, fresh[:quota]))
    with engine.begin() as conn:
        settings_store.put(conn, f"feed_stats.{lang}", history)
    plan: list[tuple[dict[str, Any], feeds.FeedEntry]] = []
    while budget > 0 and any(entries for _, entries in queues):
        for feed, entries in queues:
            if entries and budget > 0:
                plan.append((feed, entries.pop(0)))
                budget -= 1

    for number, (feed, entry) in enumerate(plan):
        name = feed.get("name") or feed["url"]
        if dry_run:
            stats.setdefault("would_read", []).append({"title": entry.title, "url": entry.url, "feed": name})
            continue
        say(start + (0.97 - start) * number / len(plan), f"reading article {number + 1} of {len(plan)}: {entry.title[:60]}")
        try:
            doc = fetchers.article(entry.url)
        except documents.DocumentError as exc:
            stats["errors"].append(f"{entry.url}: {exc}"[:200])
            continue
        with engine.begin() as conn:
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
        fetchers.pause(PAUSE_SECONDS / 2)


def prune(conn: Connection, days: int, lang: str | None = None) -> int:
    """Remove discovered items nobody opened, older than `days`: dropped ones (so they can be re-checked as your level
    moves) and measured candidates. Estimated catalogue entries stay; things you dismissed yourself, added or watched
    are never removed."""
    result = conn.execute(
        text(
            "DELETE FROM content_items WHERE origin = 'scraper' AND status IN ('candidate', 'dismissed') "
            "AND analysis_status = 'done' AND last_opened_at IS NULL AND (:l IS NULL OR language_code = :l) "
            "AND COALESCE(json_extract(metadata_json, '$.dismissed_by_you'), 0) = 0 "
            "AND added_at < strftime('%Y-%m-%dT%H:%M:%fZ', 'now', :age) "
            "AND NOT EXISTS (SELECT 1 FROM activity_sessions s WHERE s.content_item_id = content_items.id)"
        ),
        {"l": lang, "age": f"-{days} days"},
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
