"""Subtitle parsing: YouTube json3 (uploaded tracks and word-timed automatic captions), WebVTT and SRT.

Automatic captions arrive as words with their own timestamps, in rolling two-line windows.
They are rebuilt into sentence cues: a cue ends at . ? ! (or …), at a speaker change, after
a long pause, or once it gets too long.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

SENTENCE_END = re.compile(r"[.?!…。！？]['\"»”)]?$")
NOISE = re.compile(r"^\s*[\[(][^\])]{1,40}[\])]\s*$")  # [Musik], (Applaus)
TAG = re.compile(r"<[^>]+>")
VTT_TIME = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{3})")
MAX_WORDS = 22
PAUSE_MS = 1200


@dataclass
class Word:
    start_ms: int
    end_ms: int
    text: str


@dataclass
class Cue:
    start_ms: int
    end_ms: int
    text: str
    words: list[Word] = field(default_factory=list)


def _time_ms(value: str) -> int:
    match = VTT_TIME.search(value)
    if not match:
        raise ValueError(f"bad timestamp: {value!r}")
    hours, minutes, seconds, millis = match.groups()
    return ((int(hours or 0) * 60 + int(minutes)) * 60 + int(seconds)) * 1000 + int(millis)


def _clean(text: str) -> str:
    text = html.unescape(TAG.sub("", text))
    return re.sub(r"\s+", " ", text).strip()


def parse_json3(raw: str) -> list[Cue]:
    data = json.loads(raw)
    events = [e for e in data.get("events", []) if e.get("segs")]
    word_timed = any("tOffsetMs" in seg for e in events for seg in e["segs"])
    if not word_timed:
        cues = []
        for event in events:
            text = _clean("".join(seg.get("utf8", "") for seg in event["segs"]))
            if text and not NOISE.match(text):
                start = int(event.get("tStartMs", 0))
                cues.append(Cue(start, start + int(event.get("dDurationMs", 2000)), text))
        return cues

    words: list[Word] = []
    speaker_breaks: set[int] = set()
    for event in events:
        base = int(event.get("tStartMs", 0))
        event_end = base + int(event.get("dDurationMs", 0))
        segs = [s for s in event["segs"] if s.get("utf8", "").strip()]
        for index, seg in enumerate(segs):
            start = base + int(seg.get("tOffsetMs", 0))
            nxt = base + int(segs[index + 1].get("tOffsetMs", 0)) if index + 1 < len(segs) else event_end
            if seg.get("isSpeakerChange"):
                speaker_breaks.add(len(words))
            words.append(Word(start, max(nxt, start + 120), seg["utf8"].strip()))
    words.sort(key=lambda w: w.start_ms)
    return segment_words(words, speaker_breaks)


def segment_words(words: list[Word], breaks: set[int] | None = None) -> list[Cue]:
    breaks = breaks or set()
    cues: list[Cue] = []
    current: list[Word] = []

    def flush() -> None:
        if current:
            text = _clean(" ".join(w.text for w in current))
            if text and not NOISE.match(text):
                cues.append(Cue(current[0].start_ms, current[-1].end_ms, text, list(current)))
            current.clear()

    for index, word in enumerate(words):
        if current and (
            index in breaks
            or word.start_ms - current[-1].end_ms > PAUSE_MS
            or len(current) >= MAX_WORDS
        ):
            flush()
        current.append(word)
        if SENTENCE_END.search(word.text):
            flush()
    flush()
    return cues


def _blocks(raw: str) -> list[list[str]]:
    return [block.strip().splitlines() for block in re.split(r"\r?\n\s*\r?\n", raw.strip()) if block.strip()]


def parse_vtt(raw: str) -> list[Cue]:
    cues = []
    for lines in _blocks(raw.lstrip("﻿")):
        timing = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if timing is None:
            continue
        start, end = (part.strip() for part in lines[timing].split("-->")[:2])
        text = _clean(" ".join(lines[timing + 1 :]))
        if text and not NOISE.match(text):
            cues.append(Cue(_time_ms(start), _time_ms(end.split()[0]), text))
    return _dedupe_rolling(cues)


def parse_srt(raw: str) -> list[Cue]:
    return parse_vtt(raw)  # same block structure; the index line is ignored


def _dedupe_rolling(cues: list[Cue]) -> list[Cue]:
    """Rolling captions repeat the previous line; drop exact repeats."""
    out: list[Cue] = []
    for cue in cues:
        if out and cue.text == out[-1].text:
            out[-1].end_ms = cue.end_ms
            continue
        out.append(cue)
    return out


def parse_file(path: Path) -> list[Cue]:
    raw = path.read_text(encoding="utf-8-sig", errors="replace")
    suffix = path.suffix.lower()
    if suffix == ".json3" or suffix == ".json":
        return parse_json3(raw)
    if suffix in {".vtt", ".srt"}:
        return parse_vtt(raw)
    raise ValueError(f"unsupported subtitle format: {path.suffix}")
