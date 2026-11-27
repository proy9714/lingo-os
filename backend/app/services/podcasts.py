"""Podcasts: find shows in your language, follow them, and get their episodes suggested at your level.

  find       the Apple Podcasts directory (its public search, no account) by name or topic, in your language's
             countries; or paste any show's RSS address
  follow     a show is a collection (kind 'podcast'); its feed is checked again at most every 12 hours
  episodes   each episode is a podcast_episode item: its audio stays at the publisher (played and downloaded from
             there, or through this laptop or server), its artwork, length and publication date come with it
  level      an episode the publisher gives a transcript for (Podcasting 2.0 <podcast:transcript>, VTT or SRT) is
             measured like any captioned video; the others are estimated from the show's measured episodes (or from
             what you usually understand by ear) until Whisper transcribes them: the best few each day, on its own,
             if transcription is turned on (Settings → Transcription)

Personal data stays local: searches send only the words you typed (and a country) to Apple's directory.
"""

from __future__ import annotations

import json
import re
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import Connection, text

from app.config import AppConfig
from app.ingest import feeds
from app.ingest.subtitles import parse_srt, parse_vtt
from app.services import calibration, content
from app.timeutil import from_iso, to_iso, utc_now

SEARCH_URL = "https://itunes.apple.com/search"
REFRESH_HOURS = 12
KEEP_EPISODES = 40  # newest episodes taken from a feed each time
MIN_MINUTES, MAX_MINUTES = 2, 120
MAX_AUDIO_BYTES = 400 * 1024 * 1024
# Apple's directory is searched per country: the main ones for each language
COUNTRIES = {
    "de": ("de", "at", "ch"), "es": ("es", "mx", "ar"), "fr": ("fr", "ca", "be"), "it": ("it",), "ro": ("ro", "md"), "pt": ("br", "pt"),
    "ru": ("ru",), "ja": ("jp",), "ko": ("kr",), "zh": ("tw", "hk", "cn"), "hi": ("in",), "bn": ("in", "bd"), "ar": ("eg", "sa", "ae"),
}
LEARNER_QUERIES = {
    "de": "Deutsch lernen", "es": "español para extranjeros", "fr": "français facile", "it": "italiano per stranieri", "ro": "limba română pentru străini",
    "pt": "português para estrangeiros", "ru": "русский язык для иностранцев", "ja": "日本語 学習者", "ko": "한국어 학습",
    "zh": "中文 学习", "hi": "हिंदी सीखें", "bn": "বাংলা শিখুন", "ar": "تعلم العربية",
}


class PodcastError(Exception):
    pass


# ------------------------------------------------------------------ finding shows


def search(lang: str, query: str | None, limit: int = 20, http: Any = httpx) -> list[dict[str, Any]]:
    """Shows matching `query` (or learner podcasts in this language when there's no query)."""
    term = (query or "").strip() or LEARNER_QUERIES.get(lang, "podcast")
    found: dict[str, dict[str, Any]] = {}
    for country in COUNTRIES.get(lang, ("us",)):
        try:
            response = http.get(
                SEARCH_URL, params={"media": "podcast", "term": term, "country": country, "limit": limit},
                headers={"User-Agent": feeds.USER_AGENT}, timeout=15,
            )
            results = response.json().get("results", []) if response.status_code == 200 else []
        except (httpx.HTTPError, ValueError):
            continue
        for r in results:
            feed = r.get("feedUrl")
            if not feed or feed in found:
                continue
            found[feed] = {
                "title": r.get("collectionName") or r.get("trackName") or "Podcast",
                "author": r.get("artistName"),
                "feed_url": feed,
                "image": r.get("artworkUrl600") or r.get("artworkUrl100"),
                "genre": r.get("primaryGenreName"),
                "episodes": r.get("trackCount"),
            }
        if len(found) >= limit:
            break
    return list(found.values())[:limit]


# ------------------------------------------------------------------ following shows


def _valid_feed_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise PodcastError("that isn't a feed address (it should start with https://)")
    return url.strip()


def subscribe(conn: Connection, lang: str, feed_url: str, fetch=feeds.fetch_text) -> dict[str, Any]:  # noqa: ANN001
    """Follow a show by its RSS address: read its feed and add its newest episodes."""
    feed_url = _valid_feed_url(feed_url)
    existing = conn.execute(
        text("SELECT id FROM collections WHERE language_code = :l AND kind = 'podcast' AND source_url = :u"), {"l": lang, "u": feed_url}
    ).scalar()
    show = feeds.parse_podcast(fetch(feed_url))
    meta = json.dumps({"image": show.image, "description": show.description, "link": show.link, "feed_language": show.language})
    if existing:
        conn.execute(text("UPDATE collections SET subscribed = 1, metadata_json = :m WHERE id = :id"), {"m": meta, "id": existing})
        collection_id = existing
    else:
        collection_id = conn.execute(
            text(
                "INSERT INTO collections (language_code, kind, title, creator, source_url, subscribed, metadata_json) "
                "VALUES (:l, 'podcast', :t, :a, :u, 1, :m)"
            ),
            {"l": lang, "t": show.title, "a": show.author, "u": feed_url, "m": meta},
        ).lastrowid
    added = _store_episodes(conn, lang, collection_id, show, origin="user_added", fetch=fetch)
    _mark_fetched(conn, collection_id)
    return {"collection_id": collection_id, "title": show.title, "added": added, **show_of(conn, collection_id)}


def unsubscribe(conn: Connection, collection_id: int) -> bool:
    """Stop following a show. Episodes you listened to stay; ones you never opened are removed."""
    found = conn.execute(text("UPDATE collections SET subscribed = 0 WHERE id = :id AND kind = 'podcast'"), {"id": collection_id}).rowcount
    conn.execute(
        text(
            "DELETE FROM content_items WHERE collection_id = :id AND type = 'podcast_episode' AND last_opened_at IS NULL "
            "AND NOT EXISTS (SELECT 1 FROM activity_sessions s WHERE s.content_item_id = content_items.id)"
        ),
        {"id": collection_id},
    )
    return bool(found)


def _mark_fetched(conn: Connection, collection_id: int) -> None:
    conn.execute(
        text("UPDATE collections SET metadata_json = json_set(metadata_json, '$.fetched_at', :t) WHERE id = :id"),
        {"t": to_iso(utc_now()), "id": collection_id},
    )


def refresh(conn: Connection, lang: str, *, force: bool = False, fetch=feeds.fetch_text) -> dict[str, Any]:  # noqa: ANN001
    """Check followed shows for new episodes (each at most every 12 hours unless forced)."""
    rows = conn.execute(
        text(
            "SELECT id, source_url, json_extract(metadata_json, '$.fetched_at') FROM collections "
            "WHERE language_code = :l AND kind = 'podcast' AND subscribed = 1"
        ),
        {"l": lang},
    ).all()
    added, errors = 0, []
    for collection_id, url, fetched in rows:
        if not force and fetched and (utc_now() - from_iso(fetched)).total_seconds() < REFRESH_HOURS * 3600:
            continue
        try:
            show = feeds.parse_podcast(fetch(url))
        except feeds.FeedError as exc:
            errors.append(str(exc))
            continue
        added += _store_episodes(conn, lang, collection_id, show, origin="scraper", fetch=fetch)
        _mark_fetched(conn, collection_id)
    return {"added": added, "errors": errors}


def _published(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return to_iso(parsedate_to_datetime(value))
    except (TypeError, ValueError):
        try:
            return to_iso(from_iso(value))
        except ValueError:
            return None


def _store_episodes(conn: Connection, lang: str, collection_id: int, show: feeds.Podcast, *, origin: str, fetch) -> int:  # noqa: ANN001
    added = 0
    for ep in show.episodes[:KEEP_EPISODES]:
        if ep.duration_sec and not (MIN_MINUTES * 60 <= ep.duration_sec <= MAX_MINUTES * 60):
            continue
        meta = {
            "enclosure_url": ep.audio_url, "enclosure_type": ep.audio_type, "enclosure_bytes": ep.audio_bytes,
            "image": ep.image, "description": ep.description, "link": ep.link,
            "transcript_urls": [u for u, _ in ep.transcripts],
        }
        inserted = conn.execute(
            text(
                "INSERT OR IGNORE INTO content_items (language_code, type, title, creator, collection_id, collection_index, origin, "
                "source, source_url, external_id, duration_sec, published_at, status, metadata_json, analysis_status) "
                "VALUES (:l, 'podcast_episode', :t, :c, :coll, :n, :o, 'podcast', :url, :guid, :d, :p, :s, :m, 'pending')"
            ),
            {
                "l": lang, "t": ep.title, "c": show.title, "coll": collection_id, "n": ep.number, "o": origin,
                "url": ep.link or ep.audio_url, "guid": ep.guid, "d": ep.duration_sec, "p": _published(ep.published),
                "s": "library" if origin == "user_added" else "candidate", "m": json.dumps(meta),
            },
        ).rowcount
        if not inserted:
            continue
        added += 1
        item_id = conn.execute(
            text("SELECT id FROM content_items WHERE source = 'podcast' AND external_id = :g"), {"g": ep.guid}
        ).scalar_one()
        if not _publisher_transcript(conn, lang, item_id, ep, fetch):
            estimate(conn, lang, [item_id])
    return added


def _publisher_transcript(conn: Connection, lang: str, item_id: int, ep: feeds.Episode, fetch) -> bool:  # noqa: ANN001
    """Use the transcript the publisher offers, when it's subtitles (VTT or SRT): the episode is then measured."""
    for url, kind in ep.transcripts:
        if not any(k in kind or url.lower().endswith("." + k) for k in ("vtt", "srt", "subrip")):
            continue
        try:
            raw = fetch(url)
        except feeds.FeedError:
            continue
        cues = parse_vtt(raw) if "vtt" in kind or url.lower().endswith(".vtt") else parse_srt(raw)
        if len(cues) < 5:
            continue
        try:
            content.save_transcript(conn, item_id, lang, "manual", "vtt" if "vtt" in kind else "srt", cues)
            content.set_metadata(conn, item_id, captions="publisher")
            content.analyze_item(conn, item_id)
            return True
        except content.ContentError:
            continue
    return False


# ------------------------------------------------------------------ level


def estimate(conn: Connection, lang: str, item_ids: list[int]) -> int:
    """An estimated level for episodes without a transcript: the show's measured episodes, or what you usually
    understand by ear. Replaced by a measurement as soon as the episode has a transcript."""
    lo, hi = calibration.window(conn, lang, "podcast_episode")
    ideal = (lo + hi) / 2
    done = 0
    for item_id in item_ids:
        row = conn.execute(
            text(
                "SELECT ci.collection_id, ci.duration_sec, (SELECT AVG(cs.coverage) FROM content_items o JOIN content_scores cs "
                " ON cs.content_item_id = o.id WHERE o.collection_id = ci.collection_id AND cs.estimated = 0), "
                "(SELECT COUNT(*) FROM content_items o JOIN content_scores cs ON cs.content_item_id = o.id "
                " WHERE o.collection_id = ci.collection_id AND cs.estimated = 0) FROM content_items ci WHERE ci.id = :i"
            ),
            {"i": item_id},
        ).first()
        if not row:
            continue
        _, duration, show_cov, measured = row
        if measured:
            coverage = (measured * show_cov + (ideal - 0.02)) / (measured + 1)
            basis = "channel3" if measured >= 3 else "channel1"
        else:
            coverage, basis = ideal - 0.02, "language"  # an untested show: assume a little harder than ideal
        coverage = max(0.5, min(0.995, coverage))
        band, fit = calibration.band_and_fit(coverage, lo, hi)
        unknown = round(4.0 * (duration or 900) / 60, 1)
        conn.execute(
            text(
                "INSERT INTO content_scores (content_item_id, profile_version, coverage, expected_unknown, i1_score, band, estimated) "
                "VALUES (:i, 0, :c, :e, :f, :b, 1) ON CONFLICT(content_item_id) DO UPDATE SET coverage = excluded.coverage, "
                "expected_unknown = excluded.expected_unknown, i1_score = excluded.i1_score, band = excluded.band "
                "WHERE content_scores.estimated = 1"
            ),
            {"i": item_id, "c": round(coverage, 4), "e": unknown, "f": fit, "b": band},
        )
        content.set_metadata(conn, item_id, level_basis=basis, level_from="show" if measured else "language")
        done += 1
    return done


# ------------------------------------------------------------------ shows and episodes


def show_of(conn: Connection, collection_id: int) -> dict[str, Any]:
    row = conn.execute(
        text(
            "SELECT c.id, c.title, c.creator, c.source_url, c.metadata_json, c.subscribed, "
            "(SELECT COUNT(*) FROM content_items e WHERE e.collection_id = c.id), "
            "(SELECT COUNT(*) FROM content_items e WHERE e.collection_id = c.id AND (e.status = 'finished' OR EXISTS "
            " (SELECT 1 FROM activity_sessions s WHERE s.content_item_id = e.id))), "
            "(SELECT MAX(published_at) FROM content_items e WHERE e.collection_id = c.id) "
            "FROM collections c WHERE c.id = :id AND c.kind = 'podcast'"
        ),
        {"id": collection_id},
    ).first()
    if not row:
        raise PodcastError("no such show")
    meta = json.loads(row[4] or "{}")
    return {
        "id": row[0], "title": row[1], "author": row[2], "feed_url": row[3], "image": meta.get("image"),
        "description": meta.get("description"), "subscribed": bool(row[5]), "episodes": row[6], "listened": row[7],
        "latest": row[8],
    }


def shows(conn: Connection, lang: str) -> list[dict[str, Any]]:
    ids = conn.execute(
        text("SELECT id FROM collections WHERE language_code = :l AND kind = 'podcast' AND subscribed = 1 ORDER BY title"), {"l": lang}
    ).scalars().all()
    return [show_of(conn, i) for i in ids]


def episodes(conn: Connection, collection_id: int, offset: int = 0, limit: int = 30) -> dict[str, Any]:
    rows = conn.execute(
        text(
            "SELECT ci.id FROM content_items ci WHERE ci.collection_id = :c AND ci.type = 'podcast_episode' "
            "ORDER BY COALESCE(ci.published_at, ci.added_at) DESC LIMIT :n OFFSET :o"
        ),
        {"c": collection_id, "n": limit, "o": offset},
    ).scalars().all()
    total = conn.execute(text("SELECT COUNT(*) FROM content_items WHERE collection_id = :c"), {"c": collection_id}).scalar() or 0
    items = [content.get_item(conn, i) for i in rows]
    return {"show": show_of(conn, collection_id), "total": total, "items": items, "next_offset": offset + len(items) if offset + len(items) < total else None}


# ------------------------------------------------------------------ audio on this laptop or server


SAFE = re.compile(r"[^A-Za-z0-9._-]")


def _audio_folder(cfg: AppConfig, item: dict[str, Any]) -> Path:
    return content.media_root(cfg) / item["language"] / "podcasts"


def local_audio(cfg: AppConfig, conn: Connection, item: dict[str, Any]) -> Path | None:  # noqa: ARG001
    """The episode's audio if it was downloaded here already."""
    folder = _audio_folder(cfg, item)
    if not folder.is_dir():
        return None
    return next((p for p in folder.glob(f"{item['id']}.*") if p.is_file() and not p.name.endswith(".part")), None)


def ensure_local_audio(conn: Connection, cfg: AppConfig, item_id: int, http: Any = httpx) -> Path:
    """Download the episode's audio here (once), for offline downloads through the phone and for Whisper."""
    item = content.get_item(conn, item_id)
    if item["type"] != "podcast_episode":
        raise PodcastError("not a podcast episode")
    cached = local_audio(cfg, conn, item)
    if cached:
        return cached
    url = (item.get("metadata") or {}).get("enclosure_url")
    if not url:
        raise PodcastError("this episode has no audio file")
    folder = _audio_folder(cfg, item)
    folder.mkdir(parents=True, exist_ok=True)
    suffix = Path(urlparse(url).path).suffix.lower()
    suffix = suffix if suffix in {".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav"} else ".mp3"
    target = folder / SAFE.sub("_", f"{item_id}{suffix}")
    part = target.with_suffix(target.suffix + ".part")
    size = 0
    try:
        with http.stream("GET", url, headers={"User-Agent": feeds.USER_AGENT}, timeout=60, follow_redirects=True) as response:
            if response.status_code != 200:
                raise PodcastError(f"the publisher answered {response.status_code}")
            with part.open("wb") as out:
                for chunk in response.iter_bytes(1 << 16):
                    size += len(chunk)
                    if size > MAX_AUDIO_BYTES:
                        raise PodcastError("this episode's audio is too large to keep")
                    out.write(chunk)
    except httpx.HTTPError as exc:
        part.unlink(missing_ok=True)
        raise PodcastError(f"couldn't download the episode: {exc}") from exc
    except PodcastError:
        part.unlink(missing_ok=True)
        raise
    part.replace(target)
    return target


def to_transcribe(conn: Connection, lang: str, limit: int = 2) -> list[int]:
    """The best-placed episodes still without a transcript (estimated): Whisper measures these first."""
    rows = conn.execute(
        text(
            "SELECT ci.id FROM content_items ci JOIN content_scores cs ON cs.content_item_id = ci.id "
            "WHERE ci.language_code = :l AND ci.type = 'podcast_episode' AND cs.estimated = 1 "
            "AND ci.status NOT IN ('dismissed', 'archived', 'finished') "
            "AND NOT EXISTS (SELECT 1 FROM jobs j WHERE j.kind = 'transcribe' AND json_extract(j.payload_json, '$.item_id') = ci.id) "
            "ORDER BY cs.i1_score DESC, ci.published_at DESC LIMIT :n"
        ),
        {"l": lang, "n": limit},
    ).scalars().all()
    return list(rows)
