"""The video catalogue: many more videos to choose from, found cheaply and measured over time.

1. Channels. Every YouTube channel listed for your language on the Comprehensible Input Wiki, every channel you've
   watched at least twice (its address is looked up once from one of your videos), and every channel whose videos
   turned out to be at your level.
2. Listing. A channel's uploads are listed in pages of 60 (one or two requests, no per-video request), a little deeper
   into its back catalogue on each run. New videos you haven't watched become candidates.
3. Estimating. A candidate's level is estimated from the channel's other videos that were measured (including the ones
   you watched), or from the level the wiki gives the channel. Estimated items are labelled as such and rank a little
   lower than measured ones.
4. Measuring. In the background, the best-ranked estimated videos get their captions fetched and are measured word by
   word; those without real captions in the language, or far off your level, are dropped. Opening a video measures it
   too.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from sqlalchemy import Connection, Engine, text

from app.db import settings_store
from app.ingest import youtube
from app.services import calibration, content
from app.services.pacing import Pacer, Stopped, fan_out, writing
from app.timeutil import from_iso, to_iso, utc_now

if TYPE_CHECKING:
    from app.services.discover import Fetchers

LIST_PAGE = 60  # uploads listed per channel per run
MAX_DEPTH = 420  # how far back into a channel's uploads the listing goes
CHANNELS_PER_RUN = 10
RESOLVE_PER_RUN = 4  # history channels whose address is looked up per run (one request each)
PAUSE = 1.5  # between YouTube requests when they run one at a time
VERIFY_PAUSE = 2.5
# With requests running side by side (Fetchers.parallel), their starts are spaced by this many seconds instead:
# about the same request rate as before, without the run waiting on each answer in turn.
PARALLEL_GAP = 0.75
STOP_AFTER_FAILURES = 3
REFUSAL_KEY = "youtube.refused_at"

# Level labels on the wiki, relative to your ideal coverage (easier content = more of it known).
LABEL_OFFSETS = (
    (("super easy", "absolute beginner", "a1"), 0.045),
    (("beginner", "a2", "easy"), 0.03),
    (("intermediate", "b1", "all levels"), 0.0),
    (("upper", "b2"), -0.03),
    (("advanced", "c1", "c2", "native"), -0.07),
)
# How much an estimate is trusted, by what it rests on: multiplies the ranking.
CONFIDENCE = {"channel3": 0.92, "channel1": 0.82, "label": 0.72, "language": 0.6}


# ------------------------------------------------------------------ shared helpers


def known_ids(conn: Connection, source: str, ids: list[str]) -> set[str]:
    out: set[str] = set()
    for start in range(0, len(ids), 500):
        chunk = ids[start : start + 500]
        rows = conn.execute(
            text(
                f"SELECT external_id FROM content_items WHERE source = :s AND external_id IN "
                f"({','.join(':i%d' % n for n in range(len(chunk)))})"
            ),
            {"s": source, **{f"i{n}": v for n, v in enumerate(chunk)}},
        ).all()
        out |= {r[0] for r in rows}
    return out


def title_key(title: str) -> str:
    return "".join(ch for ch in title.casefold() if ch.isalnum())


def watched_titles(conn: Connection, lang: str) -> set[str]:
    """Titles of everything you've watched: sessions tracked here and rows imported from the tracker CSVs."""
    rows = conn.execute(
        text(
            "SELECT s.title FROM activity_sessions s WHERE s.language_code = :l AND s.title IS NOT NULL "
            "UNION SELECT ci.title FROM content_items ci WHERE ci.language_code = :l "
            "AND EXISTS (SELECT 1 FROM activity_sessions s WHERE s.content_item_id = ci.id)"
        ),
        {"l": lang},
    ).all()
    return {key for (title,) in rows if title and len(key := title_key(title)) >= 8}


def name_key(name: str | None) -> str:
    return "".join(ch for ch in (name or "").casefold() if ch.isalnum())


REFUSALS_KEY = "youtube.refusals"  # refusals in a row: the pause doubles each time (1, 2, 4 … 12 hours)


def refusal_pause_hours(conn: Connection) -> float:
    return float(min(12, 2 ** max(0, int(settings_store.get(conn, REFUSALS_KEY, 1) or 1) - 1)))


def youtube_refused_recently(conn: Connection, hours: float | None = None) -> bool:
    at = settings_store.get(conn, REFUSAL_KEY)
    wait = refusal_pause_hours(conn) if hours is None else hours
    return bool(at) and (utc_now() - from_iso(at)).total_seconds() < wait * 3600


def _mark_refused(engine: Engine) -> None:
    with writing(engine) as conn:
        settings_store.put(conn, REFUSAL_KEY, to_iso(utc_now()))
        settings_store.put(conn, REFUSALS_KEY, int(settings_store.get(conn, REFUSALS_KEY, 0) or 0) + 1)


def _mark_answered(engine: Engine) -> None:
    """YouTube answered normally again: the next refusal starts with a short pause."""
    with writing(engine) as conn:
        if settings_store.get(conn, REFUSALS_KEY):
            settings_store.put(conn, REFUSALS_KEY, 0)


def _is_refusal(exc: Exception) -> bool:
    message = str(exc).lower()
    return "confirm you" in message or "sign in" in message or "429" in message or "too many requests" in message


# ------------------------------------------------------------------ the right language

# Names a title uses for each language (in English, in the language itself, and in a few others): the catalogue's.
def _language_words() -> dict[str, tuple[str, ...]]:
    from app.languages.registry import CATALOG

    return {spec.code: spec.names for spec in CATALOG}


LANGUAGE_WORDS = _language_words()
# Other languages channels often teach alongside (English only when it's clearly the subject).
OTHER_WORDS = (
    "french", "français", "französisch", "francés", "italian", "italiano", "italienisch", "korean", "한국어",
    "chinese", "mandarin", "中文", "portuguese", "português", "russian", "русский", "arabic", "dutch", "niederländisch",
    "turkish", "türkisch", "polish", "hindi", "swedish", "norwegian", "danish", "greek",
    "learn english", "english lesson", "englisch lernen", "aprender inglés", "英語",
)


def other_language_title(title: str, lang: str) -> bool:
    """A title about another language (e.g. 'Japanese Basic II' from a channel that also teaches German)."""
    low = title.casefold()
    if any(word in low for word in LANGUAGE_WORDS.get(lang, ())):
        return False
    others = [w for code, words in LANGUAGE_WORDS.items() if code != lang for w in words] + list(OTHER_WORDS)
    return any(word in low for word in others)


def caption_failures(conn: Connection, lang: str) -> dict[str, tuple[int, int]]:
    """Per channel: (videos checked, videos without captions in this language)."""
    rows = conn.execute(
        text(
            "SELECT creator, COUNT(*), SUM(CASE WHEN json_extract(metadata_json, '$.captions') = 'none' THEN 1 ELSE 0 END) "
            "FROM content_items WHERE language_code = :l AND source = 'youtube' AND origin = 'scraper' "
            "AND json_extract(metadata_json, '$.captions') IS NOT NULL AND creator IS NOT NULL GROUP BY creator"
        ),
        {"l": lang},
    ).all()
    return {name_key(r[0]): (r[1], r[2] or 0) for r in rows}


# ------------------------------------------------------------------ channels


def channel_sources(conn: Connection, lang: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            "SELECT id, name, target, level_label, last_fetched_at, config_json FROM content_sources "
            "WHERE language_code = :l AND kind = 'youtube_channel' AND enabled = 1"
        ),
        {"l": lang},
    ).all()
    out = []
    for r in rows:
        config = json.loads(r[5] or "{}")
        out.append({"id": r[0], "name": r[1], "target": r[2], "level_label": r[3], "last_fetched_at": r[4], "config": config})
    return out


def _source_names(sources: list[dict[str, Any]]) -> set[str]:
    names = set()
    for s in sources:
        names.add(name_key(s["name"]))
        if s["config"].get("channel"):
            names.add(name_key(s["config"]["channel"]))
    return names


def history_channels(conn: Connection, lang: str, min_watched: int = 2) -> list[tuple[str, int, str]]:
    """Channels you've watched at least `min_watched` videos of: (name, videos watched, one video id)."""
    rows = conn.execute(
        text(
            "SELECT ci.creator, COUNT(*), MAX(ci.external_id) FROM content_items ci WHERE ci.language_code = :l "
            "AND ci.source = 'youtube' AND ci.creator IS NOT NULL "
            "AND EXISTS (SELECT 1 FROM activity_sessions s WHERE s.content_item_id = ci.id) "
            "GROUP BY ci.creator HAVING COUNT(*) >= :n ORDER BY COUNT(*) DESC"
        ),
        {"l": lang, "n": min_watched},
    ).all()
    return [(r[0], r[1], r[2]) for r in rows]


def add_channel(conn: Connection, lang: str, name: str, url: str, via: str) -> bool:
    exists = conn.execute(
        text("SELECT 1 FROM content_sources WHERE kind = 'youtube_channel' AND target = :t"), {"t": url}
    ).first()
    if exists:
        return False
    conn.execute(
        text(
            "INSERT INTO content_sources (language_code, kind, name, target, origin, enabled, fetch_every_hours, config_json) "
            "VALUES (:l, 'youtube_channel', :n, :t, 'discovered', 1, 24, :c)"
        ),
        {"l": lang, "n": name[:200], "t": url, "c": json.dumps({"via": via, "channel": name})},
    )
    return True


def youtube_pacer(fetchers: Fetchers) -> Pacer:
    """Request pacing for YouTube: a gap between starts when requests overlap, the old pause when they don't."""
    parallel = max(1, int(getattr(fetchers, "parallel", 1) or 1))
    return Pacer(PARALLEL_GAP if parallel > 1 else 0.0, fetchers.pause)


def _workers(fetchers: Fetchers) -> int:
    return max(1, int(getattr(fetchers, "parallel", 1) or 1))


def resolve_history_channels(engine: Engine, lang: str, fetchers: Fetchers, limit: int = RESOLVE_PER_RUN) -> list[str]:
    """Add the channels you watch (that aren't sources yet): one request each, to read the channel's address."""
    with engine.connect() as conn:
        known = _source_names(channel_sources(conn, lang))
        tried = set(settings_store.get(conn, f"catalog.resolved.{lang}", []) or [])
        todo = [(n, c, v) for n, c, v in history_channels(conn, lang) if name_key(n) not in known and name_key(n) not in tried]
    added = []
    workers = _workers(fetchers)
    pacer = youtube_pacer(fetchers)
    for (name, _count, _video), info, error in fan_out(
        todo[:limit], lambda t: fetchers.info(t[2]), workers=workers, pacer=pacer, name="yt-info"
    ):
        if error is not None:
            if isinstance(error, youtube.YouTubeError) and _is_refusal(error):
                _mark_refused(engine)
                break
            if isinstance(error, (youtube.YouTubeError, Stopped)):
                continue
            raise error
        url = (info.raw or {}).get("channel_url") or (info.raw or {}).get("uploader_url")
        with writing(engine) as conn:
            tried.add(name_key(name))
            settings_store.put(conn, f"catalog.resolved.{lang}", sorted(tried))
            if url and add_channel(conn, lang, name, url, "history"):
                added.append(name)
        if workers == 1:
            fetchers.pause(PAUSE)
    return added


def _channel_order(sources: list[dict[str, Any]], affinity: Callable[[str], float]) -> list[dict[str, Any]]:
    """Channels you like first, then those not listed for longest."""

    def key(source: dict[str, Any]) -> tuple[float, str]:
        liked = affinity(source["config"].get("channel") or source["name"])
        return (-round(liked, 1), source["last_fetched_at"] or "")

    return sorted(sources, key=key)


def list_channels(
    engine: Engine,
    cfg_settings: dict[str, Any],
    lang: str,
    fetchers: Fetchers,
    *,
    affinity: Callable[[str], float] = lambda name: 0.0,
    channels: int = CHANNELS_PER_RUN,
    say: Callable[[float, str], None] = lambda f, m: None,
    span: tuple[float, float] = (0.05, 0.4),
) -> dict[str, Any]:
    """List uploads of up to `channels` channels; new, unwatched videos become (estimated) candidates."""
    stats = {"channels": 0, "listed": 0, "new": 0, "errors": [], "refused": False}
    with engine.connect() as conn:
        order = _channel_order(channel_sources(conn, lang), affinity)[:channels]
        seen_titles = watched_titles(conn, lang)
    lo, hi = float(cfg_settings["min_minutes"]) * 60, float(cfg_settings["max_minutes"]) * 60

    def listing(source: dict[str, Any]) -> list[youtube.Listing]:
        count = min(MAX_DEPTH, int(source["config"].get("depth", 0)) + LIST_PAGE)
        if fetchers.channel_uploads is youtube.channel_uploads:  # the real one: titles as shown in this language
            return youtube.channel_uploads(source["target"], count, 1, lang=lang)
        return fetchers.channel_uploads(source["target"], count, 1)

    workers = _workers(fetchers)
    say(span[0], f"listing {len(order)} channels")
    for number, (source, result, error) in enumerate(
        fan_out(order, listing, workers=workers, pacer=youtube_pacer(fetchers), name="yt-list")
    ):
        say(span[0] + (span[1] - span[0]) * (number + 1) / max(1, len(order)), f"listed {source['name'][:50]}")
        depth = int(source["config"].get("depth", 0))
        if isinstance(error, Stopped):
            continue
        if error is not None and not isinstance(error, youtube.YouTubeError):
            raise error
        if error is None:
            found = result or []
            status = f"ok, {len(found)} listed"
        else:
            found, status = [], f"error: {error}"[:200]
            stats["errors"].append(f"{source['name']}: {error}"[:200])
            if _is_refusal(error):
                stats["refused"] = True
                _mark_refused(engine)
        stats["channels"] += 1
        stats["listed"] += len(found)
        fresh = [v for v in found if not v.duration or lo <= v.duration <= hi]
        with writing(engine) as conn:
            known = known_ids(conn, "youtube", [v.video_id for v in fresh])
            new = 0
            added: list[int] = []
            for video in fresh:
                if video.video_id in known or title_key(video.title) in seen_titles or other_language_title(video.title, lang):
                    continue
                item_id = content.upsert_youtube(
                    conn, lang, video.video_id, title=video.title, channel=video.channel or source["config"].get("channel") or source["name"],
                    duration=video.duration, origin="scraper", status="candidate",
                )
                conn.execute(text("UPDATE content_items SET source_id = :s WHERE id = :i"), {"s": source["id"], "i": item_id})
                content.set_metadata(conn, item_id, discovered_via=f"channel: {source['name']}", channel_url=video.channel_url or source["target"])
                added.append(item_id)
                new += 1
            stats["new"] += new
            # estimate right away, so this channel's finds join the suggestions while the search goes on
            estimate_scores(conn, lang, added)
            config = {**source["config"], "depth": min(MAX_DEPTH, depth + LIST_PAGE) if found else depth}
            conn.execute(
                text("UPDATE content_sources SET last_fetched_at = :t, last_status = :s, config_json = :c WHERE id = :i"),
                {"t": to_iso(utc_now()), "s": f"{status}, {new} new", "c": json.dumps(config), "i": source["id"]},
            )
        if stats["refused"]:
            break
        if workers == 1:
            fetchers.pause(PAUSE)
    return stats


def add_listings(engine: Engine, lang: str, listings: list[tuple[youtube.Listing, str]], cfg_settings: dict[str, Any]) -> int:
    """Search results become candidates too (estimated if their channel is known, else measured first)."""
    lo, hi = float(cfg_settings["min_minutes"]) * 60, float(cfg_settings["max_minutes"]) * 60
    with writing(engine) as conn:
        known = known_ids(conn, "youtube", [v.video_id for v, _ in listings])
        seen_titles = watched_titles(conn, lang)
        new = 0
        added: list[int] = []
        for video, via in listings:
            if video.video_id in known or title_key(video.title) in seen_titles or other_language_title(video.title, lang):
                continue
            if video.duration and not lo <= video.duration <= hi:
                continue
            item_id = content.upsert_youtube(
                conn, lang, video.video_id, title=video.title, channel=video.channel, duration=video.duration,
                origin="scraper", status="candidate",
            )
            content.set_metadata(conn, item_id, discovered_via=via, channel_url=video.channel_url)
            known.add(video.video_id)
            added.append(item_id)
            new += 1
        estimate_scores(conn, lang, added)
    return new


# ------------------------------------------------------------------ estimating


def _label_offset(label: str | None) -> float | None:
    low = (label or "").casefold()
    for words, offset in LABEL_OFFSETS:
        if any(w in low for w in words):
            return offset
    return None


def estimate_scores(conn: Connection, lang: str, item_ids: list[int] | None = None) -> int:
    """(Re)estimate the level of every candidate video that hasn't been measured. Returns how many have an estimate.

    `item_ids` limits it to those videos: used while a search runs, so new finds show up as soon as they're listed.
    """
    if item_ids is not None and not item_ids:
        return 0
    ideal = calibration.ideal(conn, lang, "listening")
    lo, hi = calibration.window(conn, lang, "youtube")
    measured = conn.execute(
        text(
            "SELECT ci.creator, COUNT(*), AVG(cs.coverage), AVG(cs.expected_unknown * 60.0 / NULLIF(ci.duration_sec, 0)) "
            "FROM content_items ci JOIN content_scores cs ON cs.content_item_id = ci.id "
            "WHERE ci.language_code = :l AND ci.source = 'youtube' AND cs.estimated = 0 AND ci.creator IS NOT NULL "
            "GROUP BY ci.creator"
        ),
        {"l": lang},
    ).all()
    by_channel = {name_key(r[0]): (r[1], r[2], r[3]) for r in measured}
    overall = conn.execute(
        text(
            "SELECT AVG(cs.coverage), AVG(cs.expected_unknown * 60.0 / NULLIF(ci.duration_sec, 0)) FROM content_items ci "
            "JOIN content_scores cs ON cs.content_item_id = ci.id WHERE ci.language_code = :l AND ci.source = 'youtube' "
            "AND cs.estimated = 0"
        ),
        {"l": lang},
    ).first()
    lang_cov = overall[0] if overall and overall[0] else ideal
    lang_rate = overall[1] if overall and overall[1] else 4.0
    channel_rows = conn.execute(
        text("SELECT id, level_label, origin FROM content_sources WHERE language_code = :l AND kind = 'youtube_channel'"),
        {"l": lang},
    ).all()
    labels = {r[0]: r[1] for r in channel_rows}
    # channels listed on the Comprehensible Input Wiki are made for learners: worth suggesting before they're measured
    curated = {r[0] for r in channel_rows if r[2] == "ci_wiki"}
    failures = caption_failures(conn, lang)
    pending = conn.execute(
        text(
            "SELECT ci.id, ci.creator, ci.source_id, ci.duration_sec, ci.title FROM content_items ci "
            "LEFT JOIN content_scores cs ON cs.content_item_id = ci.id "
            "WHERE ci.language_code = :l AND ci.source = 'youtube' AND ci.status = 'candidate' "
            "AND ci.analysis_status != 'done' AND (cs.content_item_id IS NULL OR cs.estimated = 1)"
        ),
        {"l": lang},
    ).all()
    if item_ids is not None:
        wanted = set(item_ids)
        pending = [row for row in pending if row[0] in wanted]
    count = 0
    for item_id, creator, source_id, duration, title in pending:
        if other_language_title(title, lang):
            conn.execute(text("UPDATE content_items SET status = 'dismissed' WHERE id = :i"), {"i": item_id})
            conn.execute(text("DELETE FROM content_scores WHERE content_item_id = :i AND estimated = 1"), {"i": item_id})
            content.set_metadata(conn, item_id, discovery="other_language")
            continue
        checked, missing = failures.get(name_key(creator), (0, 0))
        if checked >= 4 and missing / checked >= 0.5:
            # most of this channel's videos had no captions in the language: measure before suggesting
            conn.execute(text("DELETE FROM content_scores WHERE content_item_id = :i AND estimated = 1"), {"i": item_id})
            continue
        stats = by_channel.get(name_key(creator))
        label = _label_offset(labels.get(source_id))
        if stats and stats[0] >= 1:
            n, mean_cov, rate = stats
            prior = ideal + label if label is not None else lang_cov
            coverage = (n * mean_cov + prior) / (n + 1)
            basis, per_minute = ("channel3" if n >= 3 else "channel1"), rate or lang_rate
        elif label is not None:
            coverage, basis, per_minute = ideal + label, "label", lang_rate
        elif source_id in curated:
            coverage, basis, per_minute = lang_cov, "language", lang_rate
        else:
            # Nothing known about this channel: measure it before suggesting it.
            conn.execute(text("DELETE FROM content_scores WHERE content_item_id = :i AND estimated = 1"), {"i": item_id})
            continue
        coverage = max(0.5, min(0.995, coverage))
        band, fit = calibration.band_and_fit(coverage, lo, hi)
        unknown = round((per_minute or 0) * (duration or 600) / 60, 1)
        conn.execute(
            text(
                "INSERT INTO content_scores (content_item_id, profile_version, coverage, expected_unknown, i1_score, band, "
                "computed_at, estimated) VALUES (:i, 0, :c, :e, :s, :b, :t, 1) ON CONFLICT(content_item_id) DO UPDATE SET "
                "coverage = excluded.coverage, expected_unknown = excluded.expected_unknown, i1_score = excluded.i1_score, "
                "band = excluded.band, computed_at = excluded.computed_at WHERE content_scores.estimated = 1"
            ),
            {"i": item_id, "c": round(coverage, 4), "e": unknown, "s": fit, "b": band, "t": to_iso(utc_now())},
        )
        content.set_metadata(conn, item_id, level_basis=basis)
        count += 1
    return count


# ------------------------------------------------------------------ measuring


def measure(conn: Connection, item_id: int, lang: str, captions: youtube.Captions | None, keep_bands: list[str]) -> str:
    """Store captions and measure the video. Returns 'kept', 'no_captions' or 'off_level'."""
    if captions is None:
        conn.execute(text("UPDATE content_items SET status = 'dismissed' WHERE id = :i AND status = 'candidate'"), {"i": item_id})
        conn.execute(text("DELETE FROM content_scores WHERE content_item_id = :i AND estimated = 1"), {"i": item_id})
        content.set_metadata(conn, item_id, captions="none", discovery="no_captions")
        return "no_captions"
    content.save_transcript(conn, item_id, lang, captions.kind, captions.fmt, captions.cues)
    content.set_metadata(conn, item_id, captions=captions.kind, caption_track=captions.track_lang)
    content.analyze_item(conn, item_id)
    band = conn.execute(text("SELECT band FROM content_scores WHERE content_item_id = :i"), {"i": item_id}).scalar()
    if band not in keep_bands:  # kept as a candidate: it fills the lists while little fits your level
        content.set_metadata(conn, item_id, discovery="off_level")
        return "off_level"
    content.set_metadata(conn, item_id, discovery="ok")
    return "kept"


def to_measure(conn: Connection, lang: str, limit: int) -> list[tuple[int, str, str]]:
    """What to measure next: the best-ranked estimated videos, plus search finds from channels not known yet."""
    from app.services.recommend import ranked

    unknown = conn.execute(
        text(
            "SELECT ci.id, ci.external_id, ci.title FROM content_items ci LEFT JOIN content_scores cs "
            "ON cs.content_item_id = ci.id WHERE ci.language_code = :l AND ci.source = 'youtube' AND ci.status = 'candidate' "
            "AND ci.analysis_status != 'done' AND cs.content_item_id IS NULL ORDER BY ci.added_at DESC, ci.id DESC LIMIT :n"
        ),
        {"l": lang, "n": limit},
    ).all()
    estimated = [i for i in ranked(conn, lang, "watch") if i.get("estimated")]
    # up to a third for finds from unknown channels, the rest for the best-ranked estimates
    n_unknown = min(len(unknown), max(1, limit // 3)) if estimated else len(unknown)
    out = [(row[0], row[1], row[2]) for row in unknown[:n_unknown]]
    out += [(i["id"], i["external_id"], i["title"]) for i in estimated[: max(0, limit - len(out))]]
    return out[:limit]


def verify(
    engine: Engine,
    lang: str,
    fetchers: Fetchers,
    keep_bands: list[str],
    *,
    limit: int = 12,
    say: Callable[[float, str], None] = lambda f, m: None,
    span: tuple[float, float] = (0.0, 1.0),
) -> dict[str, Any]:
    stats = {"checked": 0, "kept": 0, "no_captions": 0, "off_level": 0, "errors": [], "refused": False, "kept_titles": []}
    with engine.connect() as conn:
        if youtube_refused_recently(conn):
            stats["refused"] = True
            return stats
        batch = to_measure(conn, lang, limit)
    consecutive = 0
    workers = _workers(fetchers)
    for number, ((item_id, video_id, title), captions, error) in enumerate(
        fan_out(batch, lambda row: fetchers.captions(row[1], lang), workers=workers, pacer=youtube_pacer(fetchers), name="yt-captions")
    ):
        say(span[0] + (span[1] - span[0]) * number / max(1, len(batch)), f"checking video {number + 1} of {len(batch)}: {title[:60]}")
        if isinstance(error, Stopped):
            continue
        if error is not None and not isinstance(error, youtube.YouTubeError):
            raise error
        stats["checked"] += 1
        if error is not None:
            stats["errors"].append(f"{video_id}: {error}"[:200])
            consecutive += 1
            if _is_refusal(error) or consecutive >= STOP_AFTER_FAILURES:
                stats["refused"] = True
                _mark_refused(engine)
                break
            if workers == 1:
                fetchers.pause(VERIFY_PAUSE)
            continue
        if stats["checked"] == 1:  # the first request of a run went through
            _mark_answered(engine)
        consecutive = 0
        # measuring (analysis and a database write) stays one at a time, while the next captions download
        with writing(engine) as conn:
            outcome = measure(conn, item_id, lang, captions, keep_bands)
        stats[outcome] += 1
        if outcome == "kept":
            stats["kept_titles"].append(title)
        if workers == 1:
            fetchers.pause(VERIFY_PAUSE)
    with writing(engine) as conn:
        promote_channels(conn, lang)
        estimate_scores(conn, lang)
    return stats


def promote_channels(conn: Connection, lang: str) -> int:
    """Channels with a video measured at your level become sources: their other videos get listed next time."""
    rows = conn.execute(
        text(
            "SELECT DISTINCT ci.creator, json_extract(ci.metadata_json, '$.channel_url') FROM content_items ci "
            "JOIN content_scores cs ON cs.content_item_id = ci.id WHERE ci.language_code = :l AND ci.source = 'youtube' "
            "AND cs.estimated = 0 AND cs.band IN ('i_plus_1', 'comfortable', 'stretch') "
            "AND json_extract(ci.metadata_json, '$.channel_url') IS NOT NULL AND ci.creator IS NOT NULL"
        ),
        {"l": lang},
    ).all()
    known = _source_names(channel_sources(conn, lang))
    added = 0
    for creator, url in rows:
        if name_key(creator) in known:
            continue
        if add_channel(conn, lang, creator, url, "found at your level"):
            known.add(name_key(creator))
            added += 1
    return added
