"""YouTube metadata and captions through yt-dlp (no API key, nothing downloaded but text).

yt-dlp needs a JavaScript runtime for YouTube; Node (already required by the frontend) is used.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.ingest.subtitles import Cue, parse_json3, parse_vtt

VIDEO_ID = re.compile(r"(?:v=|youtu\.be/|shorts/|embed/|live/|^)([A-Za-z0-9_-]{11})(?:[?&#/]|$)")
PREFERRED_EXTS = ("json3", "vtt", "srt")


class YouTubeError(RuntimeError):
    pass


@dataclass
class VideoInfo:
    video_id: str
    title: str
    channel: str | None
    duration: int | None
    language: str | None
    thumbnail: str | None
    raw: dict[str, Any]


@dataclass
class Captions:
    kind: str  # 'manual' | 'auto_caption'
    track_lang: str
    fmt: str
    cues: list[Cue]


def parse_video_id(value: str) -> str | None:
    match = VIDEO_ID.search(value.strip())
    return match.group(1) if match else None


def _ydl(**extra: Any):  # imported lazily: yt-dlp is slow to import
    from yt_dlp import YoutubeDL

    return YoutubeDL(
        {
            "skip_download": True,
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "js_runtimes": {"node": {}},
            "socket_timeout": 20,
            **extra,
        }
    )


@dataclass
class Listing:
    """One entry of a search or channel listing (flat: no per-video request)."""

    video_id: str
    title: str
    channel: str | None
    duration: int | None
    channel_url: str | None = None


def _channel_url(entry: dict[str, Any], info: dict[str, Any]) -> str | None:
    url = entry.get("channel_url") or entry.get("uploader_url")
    if url:
        return url
    channel_id = entry.get("channel_id") or info.get("channel_id")
    if channel_id:
        return f"https://www.youtube.com/channel/{channel_id}"
    return info.get("channel_url") or info.get("uploader_url")


def _flat(url: str, limit: int, start: int = 1) -> list[Listing]:
    try:
        with _ydl(extract_flat="in_playlist", playliststart=start, playlistend=start + limit - 1, noplaylist=False) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        raise YouTubeError(_short(exc)) from exc
    out = []
    for entry in (info or {}).get("entries") or []:
        video_id = entry.get("id")
        if not video_id or len(video_id) != 11:
            continue
        out.append(
            Listing(
                video_id=video_id,
                title=entry.get("title") or video_id,
                channel=entry.get("channel") or entry.get("uploader") or info.get("channel") or info.get("uploader"),
                duration=int(entry["duration"]) if entry.get("duration") else None,
                channel_url=_channel_url(entry, info or {}),
            )
        )
    return out[:limit]


def search(query: str, limit: int = 10) -> list[Listing]:
    """YouTube search results for `query` (yt-dlp's ytsearch, no API key)."""
    return _flat(f"ytsearch{limit}:{query}", limit)


def channel_uploads(channel_url: str, limit: int = 10, start: int = 1) -> list[Listing]:
    """A channel's uploads from its /videos tab, newest first: entries start … start + limit - 1."""
    url = channel_url.rstrip("/")
    for suffix in ("/featured", "/videos", "/streams", "/shorts"):
        if url.endswith(suffix):
            url = url[: -len(suffix)]
    return _flat(url + "/videos", limit, start)


def fetch_info(video_id: str) -> VideoInfo:
    try:
        with _ydl() as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
    except Exception as exc:  # yt-dlp raises many error types
        raise YouTubeError(_short(exc)) from exc
    return VideoInfo(
        video_id=video_id,
        title=info.get("title") or video_id,
        channel=info.get("channel") or info.get("uploader"),
        duration=info.get("duration"),
        language=info.get("language"),
        thumbnail=info.get("thumbnail"),
        raw=info,
    )


def _pick(tracks: dict[str, list[dict[str, Any]]], keys: list[str]) -> tuple[str, dict[str, Any]] | None:
    for key in keys:
        for track_lang, formats in tracks.items():
            if track_lang != key:
                continue
            for ext in PREFERRED_EXTS:
                fmt = next((f for f in formats if f.get("ext") == ext and f.get("url")), None)
                if fmt:
                    return track_lang, fmt
    return None


def choose_track(info: dict[str, Any], lang: str, strict: bool = False) -> tuple[str, str, dict[str, Any]] | None:
    """Uploaded subtitles first, then YouTube's own-language automatic captions.

    `strict` (used for discovery) refuses YouTube's machine-translated tracks: an automatic track only counts when it
    is the video's original language, so an English video with auto-translated German captions is not "German".
    """
    spoken = (info.get("language") or "").split("-")[0]
    if strict and spoken and spoken != lang:
        return None  # e.g. an English lesson with Spanish subtitles: the subtitles are a translation
    manual = info.get("subtitles") or {}
    manual_keys = [lang] + sorted(k for k in manual if k.startswith(f"{lang}-"))
    picked = _pick(manual, manual_keys)
    if picked:
        return "manual", picked[0], picked[1]
    auto = info.get("automatic_captions") or {}
    keys = [f"{lang}-orig"] + ([lang] if not strict or spoken == lang else [])
    picked = _pick(auto, keys)
    if picked:
        return "auto_caption", picked[0], picked[1]
    return None


def fetch_captions(video_id: str, lang: str, info: VideoInfo | None = None, strict: bool = False) -> Captions | None:
    info = info or fetch_info(video_id)
    choice = choose_track(info.raw, lang, strict)
    if choice is None:
        return None
    kind, track_lang, fmt = choice
    try:
        with _ydl() as ydl:
            raw = ydl.urlopen(fmt["url"]).read().decode("utf-8", errors="replace")
    except Exception as exc:
        raise YouTubeError(_short(exc)) from exc
    cues = parse_json3(raw) if fmt["ext"] == "json3" else parse_vtt(raw)
    return Captions(kind=kind, track_lang=track_lang, fmt=fmt["ext"], cues=cues) if cues else None


def _short(exc: Exception) -> str:
    message = str(exc).replace("ERROR: ", "").strip()
    return message.splitlines()[0][:300] if message else exc.__class__.__name__
