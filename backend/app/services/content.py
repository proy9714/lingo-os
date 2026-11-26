"""Library: content items, transcripts, local media, and analysis of what each item actually says."""

from __future__ import annotations

import json
import shutil
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, bindparam, text

from app.config import AppConfig
from app.services import calibration
from app.engine.evidence import sample_running_words
from app.engine.knowledge import knowledge_p
from app.engine.profile import get_profile
from app.engine.vocab_model import DEFAULT_K
from app.ingest.subtitles import Cue, parse_file
from app.languages import analyze
from app.services.annotate import annotate_segments, best_rank
from app.timeutil import to_iso, utc_now

ANALYZER_VERSION = "2"
VIDEO_EXT = {".mp4", ".webm", ".mkv", ".mov", ".m4v"}
AUDIO_EXT = {".mp3", ".m4a", ".ogg", ".opus", ".wav", ".flac", ".aac"}
SUB_EXT = (".vtt", ".srt")


class ContentError(ValueError):
    pass


# ------------------------------------------------------------------ items


def upsert_youtube(
    conn: Connection,
    lang: str,
    video_id: str,
    *,
    title: str,
    channel: str | None,
    duration: int | None,
    origin: str = "user_added",
    status: str = "library",
    finished: str | None = None,
) -> int:
    collection_id = _channel_collection(conn, lang, channel) if channel else None
    conn.execute(
        text(
            "INSERT OR IGNORE INTO content_items (language_code, type, title, creator, collection_id, origin, source, "
            "source_url, external_id, duration_sec, status, finished_at) VALUES (:lang, 'youtube', :title, :creator, "
            ":coll, :origin, 'youtube', :url, :vid, :dur, :status, :finished)"
        ),
        {
            "lang": lang, "title": title, "creator": channel, "coll": collection_id, "origin": origin,
            "url": f"https://www.youtube.com/watch?v={video_id}", "vid": video_id, "dur": duration,
            "status": status, "finished": finished,
        },
    )
    item_id = conn.execute(
        text("SELECT id FROM content_items WHERE source = 'youtube' AND external_id = :vid"), {"vid": video_id}
    ).scalar_one()
    if duration:
        conn.execute(
            text("UPDATE content_items SET duration_sec = COALESCE(duration_sec, :d) WHERE id = :id"),
            {"d": duration, "id": item_id},
        )
    return item_id


def _channel_collection(conn: Connection, lang: str, channel: str) -> int:
    existing = conn.execute(
        text("SELECT id FROM collections WHERE language_code = :l AND kind = 'youtube_channel' AND title = :t LIMIT 1"),
        {"l": lang, "t": channel},
    ).scalar()
    if existing:
        return existing
    return conn.execute(
        text("INSERT INTO collections (language_code, kind, title) VALUES (:l, 'youtube_channel', :t)"),
        {"l": lang, "t": channel},
    ).lastrowid


# Watched = played to 90% here (status 'finished'), marked as watched by hand (also 'finished'), or listed in the
# Immersion Tracker history. Opening a video and leaving early doesn't count: it stays in suggestions.
WATCHED_SQL = (
    "(ci.status = 'finished' OR EXISTS (SELECT 1 FROM activity_sessions ws WHERE ws.content_item_id = ci.id "
    "AND ws.tracking = 'import'))"
)


def is_watched(conn: Connection, item_id: int) -> bool:
    return bool(conn.execute(text(f"SELECT {WATCHED_SQL} FROM content_items ci WHERE ci.id = :i"), {"i": item_id}).scalar())


_ITEM_COLUMNS = (
    "ci.id, ci.language_code, ci.type, ci.title, ci.creator, ci.source, ci.source_url, ci.external_id, ci.local_path, "
    "ci.duration_sec, ci.status, ci.progress, ci.position_ref, ci.analysis_status, ci.last_opened_at, ci.metadata_json, "
    "(SELECT COUNT(*) FROM activity_sessions s WHERE s.content_item_id = ci.id AND s.is_baseline = 0), "
    "(SELECT MAX(s.started_at) FROM activity_sessions s WHERE s.content_item_id = ci.id), "
    "(SELECT kind FROM transcripts t WHERE t.content_item_id = ci.id AND t.is_primary = 1), "
    "cs.coverage, cs.expected_unknown, cs.band, ca.speech_wpm, ci.word_count, ci.page_count, ci.perceived_difficulty, "
    "COALESCE(cs.estimated, 0)"
)
_ITEM_KEYS = (
    "id", "language", "type", "title", "creator", "source", "url", "external_id", "local_path", "duration_sec",
    "status", "progress", "position_ref", "analysis_status", "last_opened_at", "metadata", "times_watched",
    "last_watched_at", "transcript_kind", "coverage", "expected_unknown", "band", "speech_wpm", "word_count", "page_count",
    "difficulty", "estimated",
)
_ITEM_FROM = (
    "FROM content_items ci LEFT JOIN content_scores cs ON cs.content_item_id = ci.id "
    "LEFT JOIN content_analysis ca ON ca.content_item_id = ci.id"
)


def _item(row: tuple) -> dict[str, Any]:
    item = dict(zip(_ITEM_KEYS, row))
    item["metadata"] = json.loads(item["metadata"] or "{}")
    return item


def get_item(conn: Connection, item_id: int) -> dict[str, Any]:
    row = conn.execute(text(f"SELECT {_ITEM_COLUMNS} {_ITEM_FROM} WHERE ci.id = :id"), {"id": item_id}).first()
    if not row:
        raise ContentError("no such item")
    return _item(row)


VIDEO_TYPES = ("youtube", "video", "audio")
PODCAST_TYPES = ("podcast_episode",)
WATCH_TYPES = VIDEO_TYPES + PODCAST_TYPES  # everything you listen to (the listening modality)
READ_TYPES = ("epub", "pdf", "article", "text")
MANGA_TYPES = ("manga_volume",)
# shelves: Watch (videos and local audio), Listen (podcasts), Read, Manga
SHELVES = {"watch": VIDEO_TYPES, "listen": PODCAST_TYPES, "read": READ_TYPES, "manga": MANGA_TYPES}


def list_items(
    conn: Connection,
    lang: str,
    *,
    q: str | None = None,
    kind: str | None = None,
    shelf: str = "watch",
    state: str = "all",
    limit: int = 60,
    offset: int = 0,
) -> dict[str, Any]:
    types = ", ".join(f"'{t}'" for t in SHELVES.get(shelf, WATCH_TYPES))
    where = ["ci.language_code = :l", f"ci.type IN ({types})", "ci.status NOT IN ('dismissed', 'archived')"]
    params: dict[str, Any] = {"l": lang, "limit": limit, "offset": offset}
    order = "COALESCE(ci.last_opened_at, (SELECT MAX(s.started_at) FROM activity_sessions s WHERE s.content_item_id = ci.id), ci.added_at)"
    if state == "watched":
        # played to 90% here, listed in the tracker, or marked "already watched"
        where.append(WATCHED_SQL)
        order = (
            "MAX(COALESCE(ci.finished_at, ''), COALESCE(ci.last_opened_at, ''), "
            "COALESCE((SELECT MAX(s.started_at) FROM activity_sessions s WHERE s.content_item_id = ci.id), ''), ci.added_at)"
        )
    elif state == "mine":  # leave out suggestions you haven't opened yet
        where.append(
            "(ci.origin != 'scraper' OR ci.last_opened_at IS NOT NULL "
            "OR EXISTS (SELECT 1 FROM activity_sessions s WHERE s.content_item_id = ci.id))"
        )
    if q:
        where.append("(ci.title LIKE :q OR ci.creator LIKE :q)")
        params["q"] = f"%{q}%"
    if kind == "local":
        where.append("ci.source = 'local'")
    elif kind == "youtube":
        where.append("ci.source = 'youtube'")
    clause = " AND ".join(where)
    total = conn.execute(text(f"SELECT COUNT(*) FROM content_items ci WHERE {clause}"), params).scalar_one()
    rows = conn.execute(
        text(
            f"SELECT {_ITEM_COLUMNS} {_ITEM_FROM} WHERE {clause} "
            f"ORDER BY {order} DESC, ci.id DESC LIMIT :limit OFFSET :offset"
        ),
        params,
    ).all()
    return {"total": total, "items": [_item(r) for r in rows]}


def record_progress(conn: Connection, item_id: int, position_ms: int | None, duration_ms: int | None) -> None:
    if position_ms is None:
        return
    progress = min(1.0, position_ms / duration_ms) if duration_ms else None
    conn.execute(
        text(
            "UPDATE content_items SET position_ref = :pos, progress = COALESCE(:prog, progress), last_opened_at = :now, "
            "status = CASE WHEN :prog >= 0.9 THEN 'finished' WHEN status IN ('library', 'candidate') THEN 'in_progress' "
            "ELSE status END, finished_at = CASE WHEN :prog >= 0.9 AND finished_at IS NULL THEN :now ELSE finished_at END "
            "WHERE id = :id"
        ),
        {"pos": f"ms:{int(position_ms)}", "prog": progress, "now": to_iso(utc_now()), "id": item_id},
    )


def set_watched(conn: Connection, item_id: int, watched: bool) -> dict[str, Any]:
    """Mark an item as already watched/finished (it leaves the suggestions and joins Watched), or undo that.

    Marking keeps the item's previous status and progress in its metadata, so undoing puts it back exactly.
    """
    item = get_item(conn, item_id)
    meta = item["metadata"]
    if watched:
        if item["status"] != "finished":
            set_metadata(conn, item_id, marked_watched=1, before_mark={"status": item["status"], "progress": item["progress"]})
        conn.execute(
            text(
                "UPDATE content_items SET status = 'finished', progress = 1.0, "
                "finished_at = COALESCE(finished_at, :now) WHERE id = :id"
            ),
            {"now": to_iso(utc_now()), "id": item_id},
        )
    elif item["status"] == "finished":
        before = meta.get("before_mark") or {}
        status = before.get("status")
        if status in (None, "finished"):
            status = "in_progress" if 0.02 < float(before.get("progress") or 0) < 0.9 else "library"
        progress = float(before.get("progress") or 0) if before else 0.0
        conn.execute(
            text("UPDATE content_items SET status = :s, progress = :p, finished_at = NULL WHERE id = :id"),
            {"s": status, "p": min(progress, 0.89), "id": item_id},
        )
        meta.pop("before_mark", None)
        meta.pop("marked_watched", None)
        conn.execute(text("UPDATE content_items SET metadata_json = :m WHERE id = :id"), {"m": json.dumps(meta), "id": item_id})
    return get_item(conn, item_id)


def mark_opened(conn: Connection, item_id: int) -> None:
    conn.execute(text("UPDATE content_items SET last_opened_at = :now WHERE id = :id"), {"now": to_iso(utc_now()), "id": item_id})


def set_metadata(conn: Connection, item_id: int, **values: Any) -> None:
    current = json.loads(
        conn.execute(text("SELECT metadata_json FROM content_items WHERE id = :id"), {"id": item_id}).scalar_one() or "{}"
    )
    current.update(values)
    conn.execute(text("UPDATE content_items SET metadata_json = :m WHERE id = :id"), {"m": json.dumps(current), "id": item_id})


# ------------------------------------------------------------------ transcripts


def save_transcript(conn: Connection, item_id: int, lang: str, kind: str, fmt: str, cues: list[Cue]) -> int:
    """Replace the item's transcript (and its searchable text) with these cues."""
    if not cues:
        raise ContentError("no subtitle lines found")
    conn.execute(text("DELETE FROM transcripts WHERE content_item_id = :id"), {"id": item_id})
    conn.execute(text("DELETE FROM content_chunks WHERE content_item_id = :id"), {"id": item_id})
    transcript_id = conn.execute(
        text(
            "INSERT INTO transcripts (content_item_id, language_code, kind, source_format, is_primary) "
            "VALUES (:id, :l, :k, :f, 1)"
        ),
        {"id": item_id, "l": lang, "k": kind, "f": fmt},
    ).lastrowid
    conn.execute(
        text(
            "INSERT INTO transcript_cues (transcript_id, seq, start_ms, end_ms, text, words_json) "
            "VALUES (:t, :seq, :s, :e, :text, :w)"
        ),
        [
            {
                "t": transcript_id, "seq": i, "s": c.start_ms, "e": max(c.end_ms, c.start_ms + 300), "text": c.text,
                "w": json.dumps([[w.start_ms, w.end_ms, w.text] for w in c.words], ensure_ascii=False) if c.words else None,
            }
            for i, c in enumerate(cues)
        ],
    )
    conn.execute(
        text("INSERT INTO content_chunks (content_item_id, seq, locator, text) VALUES (:id, :seq, :loc, :text)"),
        [{"id": item_id, "seq": i, "loc": f"ms:{c.start_ms}", "text": c.text} for i, c in enumerate(cues)],
    )
    return transcript_id


def cues_of(conn: Connection, item_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            "SELECT tc.id, tc.seq, tc.start_ms, tc.end_ms, tc.text FROM transcript_cues tc JOIN transcripts t "
            "ON t.id = tc.transcript_id WHERE t.content_item_id = :id AND t.is_primary = 1 ORDER BY tc.seq"
        ),
        {"id": item_id},
    ).all()
    return [dict(zip(("id", "seq", "start_ms", "end_ms", "text"), r)) for r in rows]


def annotated_transcript(conn: Connection, item_id: int) -> dict[str, Any]:
    item = get_item(conn, item_id)
    cues = cues_of(conn, item_id)
    if not cues:
        return {"item": item, "cues": [], "summary": None}
    tokens, summary = annotate_segments(conn, item["language"], [c["text"] for c in cues])
    for cue, own in zip(cues, tokens):
        cue["tokens"] = own
    return {"item": item, "cues": cues, "summary": summary}


def chunks_of(conn: Connection, item_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        text("SELECT seq, locator, text FROM content_chunks WHERE content_item_id = :id ORDER BY seq"), {"id": item_id}
    ).all()
    return [{"seq": r[0], "locator": r[1], "text": r[2]} for r in rows]


def text_segments(conn: Connection, item_id: int) -> list[str]:
    """The item's text: transcript lines for media, paragraphs for books and articles."""
    cues = cues_of(conn, item_id)
    return [c["text"] for c in cues] if cues else [c["text"] for c in chunks_of(conn, item_id)]


# ------------------------------------------------------------------ local media


def media_root(cfg: AppConfig) -> Path:
    return cfg.data_dir / "library" / "media"


def _probe_duration(path: Path) -> int | None:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, timeout=20,
        ).stdout.strip()
        return int(float(out)) if out else None
    except (subprocess.SubprocessError, ValueError):
        return None


def scan_media(conn: Connection, cfg: AppConfig) -> dict[str, Any]:
    """Register media in data/library/media/<lang>/ ; a same-named .srt/.vtt becomes its transcript."""
    root = media_root(cfg)
    added, transcribed, skipped = [], 0, []
    for lang in cfg.language_codes:
        folder = root / lang
        folder.mkdir(parents=True, exist_ok=True)
        for path in sorted(folder.rglob("*")):
            suffix = path.suffix.lower()
            if suffix not in VIDEO_EXT | AUDIO_EXT:
                continue
            rel = path.relative_to(cfg.data_dir).as_posix()
            existing = conn.execute(
                text("SELECT id FROM content_items WHERE source = 'local' AND external_id = :rel"), {"rel": rel}
            ).scalar()
            item_id = existing or conn.execute(
                text(
                    "INSERT INTO content_items (language_code, type, title, origin, source, external_id, local_path, "
                    "duration_sec) VALUES (:l, :type, :title, 'user_added', 'local', :rel, :rel, :dur)"
                ),
                {"l": lang, "type": "video" if suffix in VIDEO_EXT else "audio", "title": path.stem, "rel": rel, "dur": _probe_duration(path)},
            ).lastrowid
            if not existing:
                added.append(rel)
            has_transcript = conn.execute(text("SELECT 1 FROM transcripts WHERE content_item_id = :id"), {"id": item_id}).first()
            if has_transcript:
                continue
            sub = next((c for ext in SUB_EXT for c in (path.with_suffix(ext), path.with_suffix(f".{lang}{ext}")) if c.exists()), None)
            if sub:
                try:
                    save_transcript(conn, item_id, lang, "user_file", sub.suffix.lstrip("."), parse_file(sub))
                    analyze_item(conn, item_id)
                    transcribed += 1
                except (ValueError, ContentError) as exc:
                    skipped.append(f"{sub.name}: {exc}")
    return {"folder": str(root), "added": added, "with_subtitles": transcribed, "problems": skipped}


def media_path(cfg: AppConfig, item: dict[str, Any]) -> Path:
    if item["source"] != "local" or not item["local_path"]:
        raise ContentError("this item has no local file")
    path = (cfg.data_dir / item["local_path"]).resolve()
    if not path.is_relative_to(media_root(cfg).resolve()) or not path.is_file():
        raise ContentError("media file not found")
    return path


# ------------------------------------------------------------------ analysis


ANALYSIS_CHAR_LIMIT = 150_000  # longer books are analysed from a sample of their opening


def analyze_item(conn: Connection, item_id: int) -> dict[str, Any] | None:
    item = get_item(conn, item_id)
    segments = text_segments(conn, item_id)
    if not segments:
        conn.execute(text("UPDATE content_items SET analysis_status = 'no_text' WHERE id = :id"), {"id": item_id})
        return None
    cues = cues_of(conn, item_id)
    lang = item["language"]
    total_chars = sum(len(s) for s in segments)
    sample, used = [], 0
    for segment in segments:
        if used >= ANALYSIS_CHAR_LIMIT:
            break
        sample.append(segment)
        used += len(segment)
    tokens, _ = analyze(lang, "\n".join(sample))
    counts: Counter[tuple[str, str]] = Counter()
    pos: dict[tuple[str, str], str] = {}
    first_at: dict[tuple[str, str], int] = {}
    ranks: dict[tuple[str, str], int | None] = {}
    for token in tokens:
        if not token.learnable or token.pos == "PROPN":
            continue
        key = (token.lemma, token.reading)
        counts[key] += 1
        pos.setdefault(key, token.pos)
        first_at.setdefault(key, token.start)
        if key not in ranks:
            ranks[key] = best_rank(lang, token.lemma, token.display, token.lookup_forms)
    word_tokens = sum(1 for t in tokens if t.is_word)

    ids = _ensure_lexemes(conn, lang, [(k[0], k[1], pos[k], ranks[k]) for k in counts])
    conn.execute(text("DELETE FROM content_lemmas WHERE content_item_id = :id"), {"id": item_id})
    conn.execute(
        text("INSERT INTO content_lemmas (content_item_id, lexeme_id, count, first_locator) VALUES (:i, :l, :c, :loc)"),
        [{"i": item_id, "l": ids[k], "c": n, "loc": None} for k, n in counts.items()],
    )
    token_ranks = sorted((ranks[k] or 100_000) for k, n in counts.items() for _ in range(n))

    def pct(q: float) -> int | None:
        return token_ranks[min(len(token_ranks) - 1, int(q * len(token_ranks)))] if token_ranks else None

    if cues:
        duration_min = (item["duration_sec"] or 0) / 60 or (cues[-1]["end_ms"] - cues[0]["start_ms"]) / 60000
    else:
        duration_min = 0
    kind = conn.execute(
        text("SELECT kind FROM transcripts WHERE content_item_id = :id AND is_primary = 1"), {"id": item_id}
    ).scalar() or item["type"]
    sample_ratio = round(min(1.0, used / total_chars), 3) if total_chars else 1.0
    if sample_ratio < 1:  # scale counts to the whole item
        word_tokens = int(word_tokens / sample_ratio)
    analysis = {
        "token_count": sum(counts.values()),
        "unique_lemmas": len(counts),
        "speech_wpm": round(word_tokens / duration_min, 1) if duration_min else None,
        "avg_sentence_len": round(word_tokens / max(1, len(sample)), 1),
        "sample_ratio": sample_ratio,
        "rank_p50": pct(0.5), "rank_p90": pct(0.9), "rank_p95": pct(0.95),
    }
    conn.execute(
        text(
            "INSERT INTO content_analysis (content_item_id, text_source, analyzer_version, token_count, unique_lemmas, "
            "sample_ratio, speech_wpm, avg_sentence_len, rank_p50, rank_p90, rank_p95, analyzed_at) VALUES (:id, :src, :v, "
            ":tc, :ul, :sr, :wpm, :asl, :p50, :p90, :p95, :now) ON CONFLICT(content_item_id) DO UPDATE SET "
            "sample_ratio = excluded.sample_ratio, text_source = excluded.text_source, "
            "analyzer_version = excluded.analyzer_version, token_count = excluded.token_count, unique_lemmas = excluded.unique_lemmas, "
            "speech_wpm = excluded.speech_wpm, avg_sentence_len = excluded.avg_sentence_len, rank_p50 = excluded.rank_p50, "
            "rank_p90 = excluded.rank_p90, rank_p95 = excluded.rank_p95, analyzed_at = excluded.analyzed_at"
        ),
        {
            "id": item_id, "src": kind, "v": ANALYZER_VERSION, "tc": analysis["token_count"], "ul": analysis["unique_lemmas"],
            "sr": sample_ratio,
            "wpm": analysis["speech_wpm"], "asl": analysis["avg_sentence_len"], "p50": analysis["rank_p50"],
            "p90": analysis["rank_p90"], "p95": analysis["rank_p95"], "now": to_iso(utc_now()),
        },
    )
    conn.execute(
        text("UPDATE content_items SET word_count = :w, analysis_status = 'done' WHERE id = :id"),
        {"w": word_tokens, "id": item_id},
    )
    analysis["score"] = score_item(conn, item_id)
    return analysis


def _ensure_lexemes(conn: Connection, lang: str, rows: list[tuple[str, str, str, int | None]]) -> dict[tuple[str, str], int]:
    conn.execute(
        text(
            "INSERT OR IGNORE INTO lexemes (language_code, lemma, reading, pos, freq_rank) VALUES (:l, :lemma, :r, :pos, :rank)"
        ),
        [{"l": lang, "lemma": lemma, "r": reading, "pos": p, "rank": rank} for lemma, reading, p, rank in rows],
    )
    ids: dict[tuple[str, str], int] = {}
    lemmas = list({lemma for lemma, *_ in rows})
    for start in range(0, len(lemmas), 500):
        for lemma, reading, lexeme_id in conn.execute(
            text("SELECT lemma, reading, id FROM lexemes WHERE language_code = :l AND lemma IN :lemmas").bindparams(
                bindparam("lemmas", expanding=True)
            ),
            {"l": lang, "lemmas": lemmas[start : start + 500]},
        ).all():
            ids[(lemma, reading)] = lexeme_id
    return ids


def score_item(conn: Connection, item_id: int) -> dict[str, Any] | None:
    """How much of this item you probably know, given your profile, statuses and listening history."""
    item = get_item(conn, item_id)
    profile = get_profile(conn, item["language"]) or {"r50": 800.0, "k": DEFAULT_K, "version": 0}
    rows = conn.execute(
        text(
            "SELECT cl.count, l.freq_rank, w.status, w.p_known, COALESCE(h.heard, 0) FROM content_lemmas cl "
            "JOIN lexemes l ON l.id = cl.lexeme_id LEFT JOIN user_words w ON w.lexeme_id = l.id "
            "LEFT JOIN (SELECT c2.lexeme_id, SUM(c2.count * x.watches) AS heard FROM content_lemmas c2 JOIN "
            "(SELECT content_item_id, COUNT(*) AS watches FROM activity_sessions WHERE content_item_id IS NOT NULL "
            "AND is_baseline = 0 GROUP BY content_item_id) x ON x.content_item_id = c2.content_item_id "
            "WHERE c2.content_item_id != :id GROUP BY c2.lexeme_id) h ON h.lexeme_id = l.id "
            "WHERE cl.content_item_id = :id"
        ),
        {"id": item_id},
    ).all()
    if not rows:
        return None
    content_tokens = sum(r[0] for r in rows)
    others = max(0, sample_running_words(conn, item_id) - content_tokens)  # function words, names, numbers: counted as known
    known = float(others)
    expected_unknown = 0.0
    for count, rank, status, p_user, heard in rows:
        p = knowledge_p(rank, status, p_user, heard, profile["r50"], profile["k"])
        known += count * p
        expected_unknown += 1 - p
    coverage = known / (content_tokens + others)
    lo, hi = calibration.window(conn, item["language"], item["type"])  # your ratings + the weekly review
    band, fit = calibration.band_and_fit(coverage, lo, hi)
    minutes = (item["duration_sec"] or 0) / 60
    score = {
        "coverage": round(coverage, 4),
        "expected_unknown": round(expected_unknown, 1),
        "unknown_density": round(expected_unknown / minutes, 2) if minutes else None,
        "i1_score": fit,
        "band": band,
    }
    conn.execute(
        text(
            "INSERT INTO content_scores (content_item_id, profile_version, coverage, expected_unknown, unknown_density, "
            "i1_score, band, computed_at, estimated) VALUES (:id, :v, :c, :e, :d, :s, :b, :now, 0) "
            "ON CONFLICT(content_item_id) DO UPDATE "
            "SET profile_version = excluded.profile_version, coverage = excluded.coverage, "
            "expected_unknown = excluded.expected_unknown, unknown_density = excluded.unknown_density, "
            "i1_score = excluded.i1_score, band = excluded.band, computed_at = excluded.computed_at, estimated = 0"
        ),
        {
            "id": item_id, "v": profile.get("version", 0), "c": score["coverage"], "e": score["expected_unknown"],
            "d": score["unknown_density"], "s": score["i1_score"], "b": band, "now": to_iso(utc_now()),
        },
    )
    return score


def rescore_language(conn: Connection, lang: str) -> int:
    ids = [
        r[0]
        for r in conn.execute(
            text("SELECT id FROM content_items WHERE language_code = :l AND analysis_status = 'done'"), {"l": lang}
        ).all()
    ]
    for item_id in ids:
        score_item(conn, item_id)
    return len(ids)
