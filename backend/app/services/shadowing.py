"""Shadowing studio (ARCHITECTURE §6.7): clips from transcript lines, recorded attempts, word-level comparison.

The reference audio is the original video segment (played by the client, never downloaded) or the browser's voice.
Recognition runs in the browser; the server compares what was heard with the line and keeps the recordings.
"""

from __future__ import annotations

import json
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, text

from app.config import AppConfig
from app.level.dictation import score

MAX_RECORDING = 20 * 1024 * 1024


class ShadowError(Exception):
    pass


def recordings_root(cfg: AppConfig) -> Path:
    return cfg.data_dir / "recordings" / "shadow"


def _fold(word: str) -> str:
    decomposed = unicodedata.normalize("NFKD", word.lower())
    return "".join(c for c in decomposed if c.isalnum())


def word_diff(lang: str, expected: str, heard: str) -> list[dict[str, Any]]:
    """Each piece of the line, marked ok when the recogniser heard it. Japanese is compared character by character."""
    from app.languages.registry import get

    spec = get(lang)
    if spec and not spec.spaced:  # Japanese, Chinese: no spaces between words
        pieces = [c for c in expected if not c.isspace()]
        keys = [_fold(c) for c in pieces]
        got = [k for k in (_fold(c) for c in heard) if k]
    else:
        pieces = expected.split()
        keys = [_fold(w) for w in pieces]
        got = [k for k in (_fold(w) for w in heard.split()) if k]
    ok = [False] * len(pieces)
    for block in SequenceMatcher(None, keys, got, autojunk=False).get_matching_blocks():
        for i in range(block.a, block.a + block.size):
            ok[i] = True
    # punctuation-only pieces never count as missed
    return [{"text": p, "ok": ok[i] or not keys[i]} for i, p in enumerate(pieces)]


def create_clip(
    conn: Connection,
    *,
    lang: str,
    text_value: str,
    content_item_id: int | None = None,
    cue_id: int | None = None,
    start_ms: int = 0,
    end_ms: int = 0,
) -> dict[str, Any]:
    clean = re.sub(r"\s+", " ", text_value).strip()
    if not clean:
        raise ShadowError("a clip needs a line of text")
    if cue_id is not None:
        existing = conn.execute(text("SELECT id FROM shadow_clips WHERE cue_id = :c"), {"c": cue_id}).scalar()
        if existing:
            return get_clip(conn, existing)
    kind = "media" if content_item_id and end_ms > start_ms else "tts"
    clip_id = conn.execute(
        text(
            "INSERT INTO shadow_clips (language_code, content_item_id, cue_id, start_ms, end_ms, text, reference_kind) "
            "VALUES (:l, :i, :c, :s, :e, :t, :k)"
        ),
        {"l": lang, "i": content_item_id, "c": cue_id, "s": start_ms, "e": end_ms, "t": clean[:500], "k": kind},
    ).lastrowid
    return get_clip(conn, clip_id)


_CLIP_SELECT = (
    "SELECT c.id, c.language_code, c.content_item_id, c.cue_id, c.start_ms, c.end_ms, c.text, c.reference_kind, c.favorite, "
    "c.practice_count, c.created_at, ci.title, ci.source, ci.external_id, ci.type, "
    "(SELECT MAX(a.text_similarity) FROM shadow_attempts a WHERE a.clip_id = c.id), "
    "(SELECT MAX(a.created_at) FROM shadow_attempts a WHERE a.clip_id = c.id) "
    "FROM shadow_clips c LEFT JOIN content_items ci ON ci.id = c.content_item_id"
)
_CLIP_KEYS = (
    "id", "language", "content_item_id", "cue_id", "start_ms", "end_ms", "text", "reference_kind", "favorite",
    "practice_count", "created_at", "item_title", "item_source", "external_id", "item_type", "best", "last_practised",
)


def get_clip(conn: Connection, clip_id: int) -> dict[str, Any]:
    row = conn.execute(text(f"{_CLIP_SELECT} WHERE c.id = :id"), {"id": clip_id}).first()
    if not row:
        raise ShadowError("no such clip")
    clip = dict(zip(_CLIP_KEYS, row))
    clip["favorite"] = bool(clip["favorite"])
    clip["attempts"] = attempts(conn, clip_id)
    return clip


def list_clips(conn: Connection, lang: str, limit: int = 100) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(f"{_CLIP_SELECT} WHERE c.language_code = :l ORDER BY c.favorite DESC, (SELECT MAX(a.created_at) FROM shadow_attempts a WHERE a.clip_id = c.id) DESC, c.created_at DESC LIMIT :n"),
        {"l": lang, "n": limit},
    ).all()
    clips = [dict(zip(_CLIP_KEYS, r)) for r in rows]
    for clip in clips:
        clip["favorite"] = bool(clip["favorite"])
    return clips


def attempts(conn: Connection, clip_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            "SELECT id, duration_ms, stt_text, text_similarity, analysis_json, self_rating, created_at FROM shadow_attempts "
            "WHERE clip_id = :c ORDER BY created_at DESC LIMIT 30"
        ),
        {"c": clip_id},
    ).all()
    return [
        {"id": r[0], "duration_ms": r[1], "heard": r[2], "similarity": r[3], "diff": json.loads(r[4] or "{}").get("diff", []),
         "self_rating": r[5], "created_at": r[6]}
        for r in rows
    ]


def add_attempt(
    conn: Connection, cfg: AppConfig, clip_id: int, *, audio: bytes, suffix: str, duration_ms: int, heard: str
) -> dict[str, Any]:
    clip = get_clip(conn, clip_id)
    if len(audio) > MAX_RECORDING:
        raise ShadowError("recordings are limited to 20 MB")
    folder = recordings_root(cfg) / str(clip_id)
    folder.mkdir(parents=True, exist_ok=True)
    count = conn.execute(text("SELECT COUNT(*) FROM shadow_attempts WHERE clip_id = :c"), {"c": clip_id}).scalar() or 0
    path = folder / f"attempt-{count + 1:03d}{suffix}"
    path.write_bytes(audio)
    heard = heard.strip()[:1000]
    similarity = score(clip["language"], clip["text"], heard) if heard else None
    diff = word_diff(clip["language"], clip["text"], heard) if heard else []
    attempt_id = conn.execute(
        text(
            "INSERT INTO shadow_attempts (clip_id, recording_path, duration_ms, stt_text, text_similarity, analysis_json) "
            "VALUES (:c, :p, :d, :h, :s, :a)"
        ),
        {
            "c": clip_id, "p": path.relative_to(cfg.data_dir).as_posix(), "d": max(0, duration_ms), "h": heard or None,
            "s": similarity, "a": json.dumps({"diff": diff}, ensure_ascii=False),
        },
    ).lastrowid
    conn.execute(text("UPDATE shadow_clips SET practice_count = practice_count + 1 WHERE id = :c"), {"c": clip_id})
    return next(a for a in attempts(conn, clip_id) if a["id"] == attempt_id)


def recording_path(cfg: AppConfig, conn: Connection, attempt_id: int) -> Path:
    rel = conn.execute(text("SELECT recording_path FROM shadow_attempts WHERE id = :a"), {"a": attempt_id}).scalar()
    if not rel:
        raise ShadowError("no such attempt")
    path = (cfg.data_dir / rel).resolve()
    if not path.is_relative_to(cfg.data_dir.resolve()) or not path.is_file():
        raise ShadowError("the recording is missing")
    return path


def set_favorite(conn: Connection, clip_id: int, favorite: bool) -> None:
    conn.execute(text("UPDATE shadow_clips SET favorite = :f WHERE id = :c"), {"f": int(favorite), "c": clip_id})


def delete_clip(conn: Connection, cfg: AppConfig, clip_id: int) -> None:
    """Removes the clip, its attempts and their recordings (the user asked for it in the UI)."""
    get_clip(conn, clip_id)
    folder = recordings_root(cfg) / str(clip_id)
    for path in folder.glob("attempt-*"):
        path.unlink(missing_ok=True)
    if folder.exists():
        try:
            folder.rmdir()
        except OSError:
            pass
    conn.execute(text("DELETE FROM shadow_clips WHERE id = :c"), {"c": clip_id})


# ------------------------------------------------------------------ shadowing a whole video or podcast episode

SHADOWABLE_TYPES = ("youtube", "video", "audio", "podcast_episode")


def sources(conn: Connection, lang: str, q: str | None = None, limit: int = 40) -> list[dict[str, Any]]:
    """Videos and podcast episodes with a transcript, to shadow line by line: the ones you're in the middle of, have
    saved for later or shadowed already first, then the ones you watched, then suggestions closest to your level."""
    types = ", ".join(f"'{t}'" for t in SHADOWABLE_TYPES)
    params: dict[str, Any] = {"l": lang, "n": limit}
    where = [
        "ci.language_code = :l", f"ci.type IN ({types})", "ci.status NOT IN ('dismissed', 'archived')",
        "EXISTS (SELECT 1 FROM transcripts t JOIN transcript_cues tc ON tc.transcript_id = t.id "
        "WHERE t.content_item_id = ci.id AND t.is_primary = 1)",
    ]
    if q and q.strip():
        where.append("(ci.title LIKE :q OR ci.creator LIKE :q)")
        params["q"] = f"%{q.strip()}%"
    rows = conn.execute(
        text(
            "SELECT ci.id, ci.type, ci.title, ci.creator, ci.source, ci.external_id, ci.duration_sec, ci.status, ci.progress, "
            "json_extract(ci.metadata_json, '$.image'), json_extract(ci.metadata_json, '$.saved_at'), cs.band, cs.coverage, "
            "(SELECT COUNT(*) FROM transcripts t JOIN transcript_cues tc ON tc.transcript_id = t.id "
            " WHERE t.content_item_id = ci.id AND t.is_primary = 1) AS lines, "
            "(SELECT COUNT(DISTINCT sc.id) FROM shadow_clips sc JOIN shadow_attempts sa ON sa.clip_id = sc.id "
            " WHERE sc.content_item_id = ci.id) AS shadowed, "
            "(SELECT MAX(sa.created_at) FROM shadow_clips sc JOIN shadow_attempts sa ON sa.clip_id = sc.id "
            " WHERE sc.content_item_id = ci.id) AS last_shadowed, "
            "CASE WHEN ci.status = 'in_progress' THEN 'in progress' "
            " WHEN json_extract(ci.metadata_json, '$.saved_at') IS NOT NULL THEN 'saved for later' "
            " WHEN ci.status = 'finished' OR ci.last_opened_at IS NOT NULL THEN 'watched' ELSE 'suggested' END AS why "
            f"FROM content_items ci LEFT JOIN content_scores cs ON cs.content_item_id = ci.id WHERE {' AND '.join(where)} "
            "ORDER BY (last_shadowed IS NULL), last_shadowed DESC, "
            " CASE why WHEN 'in progress' THEN 0 WHEN 'saved for later' THEN 1 WHEN 'watched' THEN 2 ELSE 3 END, "
            " COALESCE(ci.last_opened_at, json_extract(ci.metadata_json, '$.saved_at'), '') DESC, "
            " ABS(COALESCE(cs.coverage, 0.9) - 0.95), ci.id DESC LIMIT :n"
        ),
        params,
    ).all()
    keys = (
        "id", "type", "title", "creator", "source", "external_id", "duration_sec", "status", "progress", "image", "saved_at",
        "band", "coverage", "lines", "shadowed", "last_shadowed", "why",
    )
    return [dict(zip(keys, r)) for r in rows]


def item_progress(conn: Connection, item_id: int) -> list[dict[str, Any]]:
    """For each line of an item you've shadowed: its clip, how many tries and your best score."""
    rows = conn.execute(
        text(
            "SELECT sc.cue_id, sc.id, COUNT(sa.id), MAX(sa.text_similarity) FROM shadow_clips sc "
            "LEFT JOIN shadow_attempts sa ON sa.clip_id = sc.id WHERE sc.content_item_id = :i AND sc.cue_id IS NOT NULL "
            "GROUP BY sc.id"
        ),
        {"i": item_id},
    ).all()
    return [{"cue_id": r[0], "clip_id": r[1], "attempts": r[2], "best": r[3]} for r in rows]
