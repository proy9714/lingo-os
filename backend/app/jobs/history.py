"""Fetch captions for the YouTube videos you've watched, analyse them, and refresh your starting estimate."""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import text

from app.engine.profile import sync_baselines
from app.ingest.youtube import YouTubeError, fetch_captions
from app.jobs.runner import JobContext, register
from app.services import content

PAUSE_SECONDS = 1.5  # be gentle with YouTube
STOP_AFTER_FAILURES = 5  # consecutive errors usually mean we're being refused; stop and report


def pending_videos(conn, lang: str | None, limit: int | None) -> list[tuple[int, str, str, str]]:
    rows = conn.execute(
        text(
            "SELECT ci.id, ci.external_id, ci.language_code, ci.title FROM content_items ci "
            "WHERE ci.source = 'youtube' AND (:lang IS NULL OR ci.language_code = :lang) "
            "AND NOT EXISTS (SELECT 1 FROM transcripts t WHERE t.content_item_id = ci.id) "
            "AND COALESCE(json_extract(ci.metadata_json, '$.captions'), '') != 'none' "  # errors are retried
            "AND EXISTS (SELECT 1 FROM activity_sessions s WHERE s.content_item_id = ci.id) "
            "ORDER BY (SELECT MAX(started_at) FROM activity_sessions s WHERE s.content_item_id = ci.id) DESC"
        ),
        {"lang": lang},
    ).all()
    return [tuple(r) for r in rows][: limit or None]


@register("fetch_history_captions")
def fetch_history_captions(ctx: JobContext) -> dict[str, Any]:
    lang = ctx.payload.get("lang")
    with ctx.engine.begin() as conn:
        videos = pending_videos(conn, lang, ctx.payload.get("limit"))
    fetched = none = errors = consecutive = 0
    last_error = None
    for index, (item_id, video_id, item_lang, title) in enumerate(videos):
        if ctx.cancelled():
            break
        ctx.progress(index / max(1, len(videos)), f"{index + 1}/{len(videos)} · {title}")
        try:
            captions = fetch_captions(video_id, item_lang)
            with ctx.engine.begin() as conn:
                if captions is None:
                    content.set_metadata(conn, item_id, captions="none")
                    none += 1
                else:
                    content.save_transcript(conn, item_id, item_lang, captions.kind, captions.fmt, captions.cues)
                    content.set_metadata(conn, item_id, captions=captions.kind, caption_track=captions.track_lang)
                    content.analyze_item(conn, item_id)
                    fetched += 1
            consecutive = 0
        except YouTubeError as exc:
            errors += 1
            consecutive += 1
            last_error = str(exc)
            with ctx.engine.begin() as conn:
                content.set_metadata(conn, item_id, captions="error", caption_error=last_error)
            if consecutive >= STOP_AFTER_FAILURES:
                break
        time.sleep(PAUSE_SECONDS)

    with ctx.engine.begin() as conn:
        sync_baselines(conn, ctx.cfg)
        for code in ctx.cfg.language_codes:
            content.rescore_language(conn, code)
    ctx.progress(1.0, "done")
    return {
        "videos": len(videos),
        "fetched": fetched,
        "no_captions": none,
        "errors": errors,
        "stopped_early": consecutive >= STOP_AFTER_FAILURES,
        "last_error": last_error,
    }
