"""Transcribe a video or audio file with Whisper, then analyse it like any captioned video."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from app.db import settings_store
from app.ingest import whisper
from app.jobs.runner import JobContext, register
from app.services import content


@register("transcribe")
def transcribe(ctx: JobContext) -> dict[str, Any]:
    item_id = int(ctx.payload["item_id"])
    with ctx.engine.connect() as conn:
        item = content.get_item(conn, item_id)
        size = settings_store.get(conn, whisper.SETTING) or "base"
    if size not in whisper.MODELS:
        raise whisper.WhisperError("Transcription is off: choose a model in Settings → Transcription.")
    if not whisper.model_ready(ctx.cfg, size):
        ctx.progress(0.02, f"downloading the speech model ({whisper.MODELS[size]['size_mb']} MB, once)")
    model = whisper.ensure_model(ctx.cfg, size)

    work = ctx.cfg.data_dir / "cache" / "audio" / str(item_id)
    try:
        if item["source"] == "youtube" and item["external_id"]:
            ctx.progress(0.1, "fetching the audio")
            audio = whisper.youtube_audio(item["external_id"], work)
        elif item["type"] == "podcast_episode":
            from app.services import podcasts

            ctx.progress(0.1, "fetching the episode")
            with ctx.engine.connect() as conn:
                audio = podcasts.ensure_local_audio(conn, ctx.cfg, item_id)  # kept: offline downloads use it too
        elif item["local_path"] and Path(item["local_path"]).exists():
            audio = Path(item["local_path"])
        else:
            raise whisper.WhisperError("There's no audio to transcribe for this item.")
        ctx.progress(0.15, "listening")
        result = whisper.transcribe(
            model, audio, item["language"], on_progress=lambda f: ctx.progress(0.15 + 0.8 * f, "listening"),
            duration=item["duration_sec"],
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)  # the downloaded audio isn't kept
    if not result.cues:
        raise whisper.WhisperError("No speech was found in this recording.")
    with ctx.engine.begin() as conn:
        content.save_transcript(conn, item_id, item["language"], "whisper", "whisper", result.cues)
        content.set_metadata(conn, item_id, captions="whisper", whisper_model=size)
        content.analyze_item(conn, item_id)
    return {"item_id": item_id, "lines": len(result.cues), "model": size}
