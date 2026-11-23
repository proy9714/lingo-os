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
from app.services import content, reading
from app.timeutil import from_iso, to_iso, utc_now

PAUSE_SECONDS = 2.0
STOP_AFTER_FAILURES = 3
WIKI_EVERY = timedelta(days=7)
DEFAULTS = {
    "per_run": 10, "articles_per_run": 4, "min_minutes": 3, "max_minutes": 45, "prune_days": 30,
    "keep_bands": ["stretch", "i_plus_1", "comfortable"],
}


@dataclass
class Fetchers:
    """Everything that touches the network, replaceable in tests."""

    search: Callable[[str, int], list[youtube.Listing]] = youtube.search
    channel_uploads: Callable[[str, int], list[youtube.Listing]] = youtube.channel_uploads
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


def _known_ids(conn: Connection, source: str, ids: list[str]) -> set[str]:
    if not ids:
        return set()
    rows = conn.execute(
        text(f"SELECT external_id FROM content_items WHERE source = :s AND external_id IN ({','.join(':i%d' % n for n in range(len(ids)))})"),
        {"s": source, **{f"i{n}": v for n, v in enumerate(ids)}},
    ).all()
    return {r[0] for r in rows}


def _band(conn: Connection, item_id: int) -> str | None:
    return conn.execute(text("SELECT band FROM content_scores WHERE content_item_id = :i"), {"i": item_id}).scalar()


def _queries(spec: dict[str, Any], level: str, run_number: int, count: int = 2) -> list[str]:
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
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    fetchers = fetchers or Fetchers()
    sources = load_sources(cfg)
    settings, spec = sources["defaults"], sources["languages"].get(lang, {})
    limit = per_run or int(settings["per_run"])
    stats: dict[str, Any] = {"language": lang, "listed": 0, "checked": 0, "added": 0, "off_level": 0, "no_captions": 0,
                             "articles_added": 0, "errors": [], "stopped_early": False, "added_titles": []}
    say = progress or (lambda message: None)

    with engine.begin() as conn:
        level = _level(conn, lang)
        run_number = conn.execute(text("SELECT COUNT(*) FROM scrape_runs WHERE language_code = :l"), {"l": lang}).scalar() or 0
        channels = conn.execute(
            text(
                "SELECT id, target, name FROM content_sources WHERE language_code = :l AND kind = 'youtube_channel' "
                "AND enabled = 1 ORDER BY COALESCE(last_fetched_at, '') LIMIT 3"
            ),
            {"l": lang},
        ).all()
        run_id = None
        if not dry_run:
            run_id = conn.execute(
                text("INSERT INTO scrape_runs (language_code, status) VALUES (:l, 'running')"), {"l": lang}
            ).lastrowid

    # 1. List candidates: wiki channels' recent uploads, then searches. Listings are cheap (one request each).
    listings: list[tuple[youtube.Listing, str]] = []
    refused = False
    for source_id, target, name in channels:
        try:
            found = fetchers.channel_uploads(target, 8)
            listings += [(item, f"channel: {name}") for item in found]
            status = f"ok, {len(found)} listed"
        except youtube.YouTubeError as exc:
            status = f"error: {exc}"[:200]
            stats["errors"].append(f"{name}: {exc}"[:200])
            refused = refused or "confirm you" in str(exc)
        if not dry_run:
            with engine.begin() as conn:
                conn.execute(
                    text("UPDATE content_sources SET last_fetched_at = :t, last_status = :s WHERE id = :i"),
                    {"t": to_iso(utc_now()), "s": status, "i": source_id},
                )
        fetchers.pause(PAUSE_SECONDS / 2)
    for query in _queries(spec, level, run_number) if not refused else []:
        try:
            listings += [(item, f"search: {query}") for item in fetchers.search(query, 8)]
        except youtube.YouTubeError as exc:
            stats["errors"].append(f"search '{query}': {exc}"[:200])
        fetchers.pause(PAUSE_SECONDS / 2)

    lo, hi = float(settings["min_minutes"]) * 60, float(settings["max_minutes"]) * 60
    unique: dict[str, tuple[youtube.Listing, str]] = {}
    for item, via in listings:
        if item.duration and not lo <= item.duration <= hi:
            continue
        unique.setdefault(item.video_id, (item, via))
    with engine.connect() as conn:
        known = _known_ids(conn, "youtube", list(unique))
    fresh = [v for k, v in unique.items() if k not in known]
    stats["listed"] = len(fresh)
    if dry_run:
        stats["would_check"] = [{"video_id": i.video_id, "title": i.title, "channel": i.channel, "via": via} for i, via in fresh[:limit]]
    else:
        # 2. Check captions and analyse, one video at a time, paced.
        consecutive = 0
        for item, via in fresh[:limit]:
            if refused:
                stats["stopped_early"] = True
                break
            say(f"checking {item.title[:60]}")
            stats["checked"] += 1
            try:
                captions = fetchers.captions(item.video_id, lang)
                consecutive = 0
            except youtube.YouTubeError as exc:
                stats["errors"].append(f"{item.video_id}: {exc}"[:200])
                consecutive += 1
                refused = consecutive >= STOP_AFTER_FAILURES or "confirm you" in str(exc)
                fetchers.pause(PAUSE_SECONDS)
                continue
            with engine.begin() as conn:
                item_id = content.upsert_youtube(
                    conn, lang, item.video_id, title=item.title, channel=item.channel, duration=item.duration,
                    origin="scraper", status="candidate",
                )
                if captions is None:
                    stats["no_captions"] += 1
                    conn.execute(text("UPDATE content_items SET status = 'dismissed' WHERE id = :i"), {"i": item_id})
                    content.set_metadata(conn, item_id, captions="none", discovered_via=via, discovery="no_captions")
                else:
                    content.save_transcript(conn, item_id, lang, captions.kind, captions.fmt, captions.cues)
                    content.set_metadata(conn, item_id, captions=captions.kind, caption_track=captions.track_lang, discovered_via=via)
                    content.analyze_item(conn, item_id)
                    if _band(conn, item_id) in settings["keep_bands"]:
                        stats["added"] += 1
                        stats["added_titles"].append(item.title)
                    else:
                        stats["off_level"] += 1
                        conn.execute(text("UPDATE content_items SET status = 'dismissed' WHERE id = :i"), {"i": item_id})
                        content.set_metadata(conn, item_id, discovery="off_level")
            fetchers.pause(PAUSE_SECONDS)

    # 3. Articles from the feeds.
    articles_left = int(settings["articles_per_run"])
    for feed in spec.get("feeds") or []:
        if articles_left <= 0:
            break
        try:
            entries = fetchers.feed(feed["url"])[:8]
        except feeds.FeedError as exc:
            stats["errors"].append(f"{feed.get('name', feed['url'])}: {exc}"[:200])
            continue
        with engine.connect() as conn:
            known_urls = _known_ids(conn, "web", [e.url for e in entries])
        for entry in entries:
            if articles_left <= 0 or entry.url in known_urls:
                continue
            if dry_run:
                stats.setdefault("would_read", []).append({"title": entry.title, "url": entry.url})
                articles_left -= 1
                continue
            say(f"reading {entry.title[:60]}")
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
                    {"s": "candidate" if keep else "dismissed", "c": feed.get("name"), "i": item_id},
                )
                content.set_metadata(conn, item_id, discovered_via=f"feed: {feed.get('name', '')}", discovery="ok" if keep else "off_level")
            articles_left -= 1
            if keep:
                stats["articles_added"] += 1
                stats["added_titles"].append(doc.title)
            else:
                stats["off_level"] += 1
            fetchers.pause(PAUSE_SECONDS / 2)

    stats["stopped_early"] = stats["stopped_early"] or refused
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


def prune(conn: Connection, days: int, lang: str | None = None) -> int:
    """Remove discovered items nobody opened, older than `days` (never anything you added or watched)."""
    result = conn.execute(
        text(
            "DELETE FROM content_items WHERE origin = 'scraper' AND status IN ('candidate', 'dismissed') "
            "AND last_opened_at IS NULL AND (:l IS NULL OR language_code = :l) "
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
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    results = {}
    for code in cfg.language_codes:
        if lang not in (None, code):
            continue
        wiki = None
        if not dry_run:
            try:
                wiki = sync_wiki(engine, cfg, code, fetchers)
            except ci_wiki.WikiError as exc:
                wiki = {"error": str(exc)}
        results[code] = {
            "wiki": wiki,
            **discover_language(engine, cfg, code, per_run=per_run, dry_run=dry_run, fetchers=fetchers, progress=progress),
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
