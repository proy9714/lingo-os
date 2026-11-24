"""Speech with native voices: /api/tts plays a sentence, /api/tts/voices lists and chooses voices."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import Connection

from app.api.deps import get_cfg, get_conn
from app.config import AppConfig
from app.db import settings_store
from app.services import tts

router = APIRouter(prefix="/api/tts", tags=["speech"])


@router.get("")
async def speak(
    request: Request,
    lang: str = Query(..., min_length=2, max_length=8),
    text: str = Query(..., min_length=1, max_length=tts.MAX_CHARS),
    rate: float = Query(1.0, ge=0.5, le=2.0),
    voice: str | None = Query(None, max_length=80, pattern=r"^[A-Za-z]{2,3}-[A-Za-z0-9-]+Neural$"),
    cfg: AppConfig = Depends(get_cfg),
) -> FileResponse:
    """The sentence as an MP3 in a native voice (the chosen one, or the language's default)."""
    if lang not in tts.LOCALES:
        raise HTTPException(status_code=422, detail=f"no voices for '{lang}'")
    # a short read, not a transaction held open while the voice service answers
    with request.app.state.engine.connect() as conn:
        chosen = voice or tts.chosen_voice(conn, lang)
        locale = tts.locale_for(conn, lang)
    try:
        if not chosen:
            chosen = tts.default_voice(await tts.voices_for(cfg, lang, locale))
        if not chosen:
            raise HTTPException(status_code=404, detail=f"no voice for '{lang}'")
        path = await tts.synthesize(cfg, text, chosen, rate)
    except tts.TtsError as exc:
        raise HTTPException(status_code=503, detail=f"Native voice unavailable: {exc}.") from exc
    return FileResponse(path, media_type="audio/mpeg", headers={"Cache-Control": "private, max-age=31536000, immutable"})


@router.get("/voices")
async def voices(
    request: Request, lang: str = Query(..., min_length=2, max_length=8), cfg: AppConfig = Depends(get_cfg)
) -> dict[str, Any]:
    with request.app.state.engine.connect() as conn:
        chosen, engine = tts.chosen_voice(conn, lang), tts.engine(conn)
        locale = tts.locale_for(conn, lang)
    try:
        options = await tts.voices_for(cfg, lang, locale)
        error = None
    except tts.TtsError as exc:
        options, error = [], str(exc)
    ids = {v["id"] for v in options}
    return {
        "language": lang,
        "engine": engine,
        "voice": chosen if chosen in ids else tts.default_voice(options),
        "voices": options,
        "error": error,
    }


class VoiceSettings(BaseModel):
    engine: str | None = Field(default=None, pattern="^(neural|device)$")
    lang: str | None = Field(default=None, min_length=2, max_length=8)
    voice: str | None = Field(default=None, max_length=80, pattern=r"^[A-Za-z]{2,3}-[A-Za-z0-9-]+Neural$")


@router.put("/settings")
def save_settings(body: VoiceSettings, conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    """Choose the engine (neural voices, or only this device's), or one language's voice."""
    if body.engine:
        settings_store.put(conn, "tts.engine", body.engine)
    if body.lang and body.voice:
        if body.lang not in tts.LOCALES or not body.voice.startswith(tts.LOCALES[body.lang].split("-")[0] + "-"):
            raise HTTPException(status_code=422, detail="That voice doesn't speak this language.")
        settings_store.put(conn, f"tts.voice.{body.lang}", body.voice)
    return {"engine": tts.engine(conn)}
