"""Text to speech with native voices.

Browsers only have the voices installed in the operating system, and a Windows laptop often has English ones only,
so German, Spanish or Japanese came out with an English accent. The laptop makes the audio instead, with Microsoft's
neural voices (the ones Edge's Read Aloud uses; no key or account). Each clip is cached under data/cache/tts, so a
sentence is only ever sent once. The phone gets the same audio through sync, and falls back to Android's own voices
when it can't reach the laptop.

Settings: `tts.engine` = "neural" (default) or "device" (only the browser's or phone's own voices),
          `tts.voice.<lang>` = a voice id such as "de-DE-TanjaNeural".
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from sqlalchemy import Connection

from app.config import AppConfig
from app.db import settings_store

def _default_locales() -> dict[str, str]:
    from app.languages.registry import CATALOG

    return {spec.code: spec.default_variant.locale for spec in CATALOG}


# The locale each language is spoken in by default (its first variety in the catalogue).
LOCALES = _default_locales()


def locale_for(conn: Connection, lang: str) -> str | None:
    """The locale of the variety this learner chose (Brazilian or European Portuguese, …)."""
    from sqlalchemy import text

    from app.languages.registry import get

    spec = get(lang)
    if not spec:
        return None
    variant = conn.execute(text("SELECT variant FROM languages WHERE code = :c"), {"c": lang}).scalar()
    return spec.variant(variant).locale
ENGINES = ("neural", "device")
MAX_CHARS = 1500
VOICE_LIST_TTL = 7 * 24 * 3600
CACHE_LIMIT_BYTES = 300 * 1024 * 1024


class TtsError(RuntimeError):
    """The voice service couldn't be reached or refused the text."""


def cache_dir(cfg: AppConfig) -> Path:
    path = cfg.data_dir / "cache" / "tts"
    path.mkdir(parents=True, exist_ok=True)
    return path


# ------------------------------------------------------------------ voices

_voices: tuple[float, list[dict[str, Any]]] | None = None
_voices_lock = asyncio.Lock()


def _short(voice: dict[str, Any]) -> dict[str, Any]:
    vid = voice["ShortName"]
    name = vid.split("-", 2)[-1].removesuffix("Neural").removesuffix("Multilingual")
    return {"id": vid, "name": name, "gender": voice.get("Gender", ""), "locale": voice.get("Locale", "")}


async def all_voices(cfg: AppConfig) -> list[dict[str, Any]]:
    """Every neural voice, cached for a week in memory and on disk (so the list works offline too)."""
    global _voices
    if _voices and time.time() - _voices[0] < VOICE_LIST_TTL:
        return _voices[1]
    async with _voices_lock:
        if _voices and time.time() - _voices[0] < VOICE_LIST_TTL:
            return _voices[1]
        stored = cache_dir(cfg) / "voices.json"
        if stored.exists() and time.time() - stored.stat().st_mtime < VOICE_LIST_TTL:
            voices = json.loads(stored.read_text(encoding="utf-8"))
        else:
            try:
                import edge_tts

                voices = [_short(v) for v in await edge_tts.list_voices()]
                stored.write_text(json.dumps(voices), encoding="utf-8")
            except Exception as exc:  # noqa: BLE001 - offline, blocked, changed: use the last list if there is one
                if not stored.exists():
                    raise TtsError(f"the voice list couldn't be loaded ({exc})") from exc
                voices = json.loads(stored.read_text(encoding="utf-8"))
        _voices = (time.time(), voices)
        return voices


async def voices_for(cfg: AppConfig, lang: str, locale: str | None = None) -> list[dict[str, Any]]:
    """The language's voices: the chosen variety's locale first, then other regions (e.g. Mexican Spanish)."""
    locale = locale or LOCALES.get(lang)
    if not locale:
        return []
    prefix = locale.split("-")[0] + "-"
    mine = [v for v in await all_voices(cfg) if v["locale"].startswith(prefix)]
    return sorted(mine, key=lambda v: (v["locale"] != locale, v["locale"], v["gender"] != "Female", v["name"]))


def default_voice(voices: list[dict[str, Any]]) -> str | None:
    return voices[0]["id"] if voices else None


def chosen_voice(conn: Connection, lang: str) -> str | None:
    return settings_store.get(conn, f"tts.voice.{lang}")


def engine(conn: Connection) -> str:
    value = settings_store.get(conn, "tts.engine", "neural")
    return value if value in ENGINES else "neural"


# ------------------------------------------------------------------ speaking

_locks: dict[str, asyncio.Lock] = {}
_writes = 0


def rate_text(rate: float) -> str:
    """1.0 → "+0%", 0.9 → "-10%" (the voice service's way of saying speed)."""
    percent = round((max(0.5, min(2.0, rate)) - 1) * 100)
    return f"{percent:+d}%"


def clip_path(cfg: AppConfig, voice: str, rate: float, text: str) -> Path:
    key = hashlib.sha256(f"{voice}|{rate_text(rate)}|{text}".encode()).hexdigest()
    return cache_dir(cfg) / key[:2] / f"{key}.mp3"


async def synthesize(cfg: AppConfig, text: str, voice: str, rate: float = 1.0) -> Path:
    """The clip for this text, voice and speed: from the cache, or made once and cached."""
    text = " ".join(text.split())[:MAX_CHARS]
    if not text:
        raise TtsError("nothing to say")
    path = clip_path(cfg, voice, rate, text)
    if path.exists():
        os.utime(path)  # recently used clips survive pruning
        return path
    lock = _locks.setdefault(path.name, asyncio.Lock())
    try:
        async with lock:
            if path.exists():
                return path
            await _make(text, voice, rate, path)
    finally:
        _locks.pop(path.name, None)
    _maybe_prune(cfg)
    return path


async def _make(text: str, voice: str, rate: float, path: Path) -> None:
    import edge_tts

    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".part")
    try:
        await edge_tts.Communicate(text, voice, rate=rate_text(rate), connect_timeout=8, receive_timeout=30).save(str(partial))
    except Exception as exc:  # noqa: BLE001 - network errors, a refused voice, an empty answer
        partial.unlink(missing_ok=True)
        raise TtsError(f"the voice service couldn't be reached ({type(exc).__name__})") from exc
    if not partial.exists() or partial.stat().st_size == 0:
        partial.unlink(missing_ok=True)
        raise TtsError("the voice service returned no audio")
    partial.replace(path)


def _maybe_prune(cfg: AppConfig) -> None:
    """Every so often, keep the cache under its size limit by removing the least recently used clips."""
    global _writes
    _writes += 1
    if _writes % 100:
        return
    clips = sorted(cache_dir(cfg).glob("*/*.mp3"), key=lambda p: p.stat().st_mtime)
    total = sum(p.stat().st_size for p in clips)
    for clip in clips:
        if total <= CACHE_LIMIT_BYTES * 0.8:
            break
        total -= clip.stat().st_size
        clip.unlink(missing_ok=True)
