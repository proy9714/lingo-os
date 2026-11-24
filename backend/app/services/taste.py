"""What you like to watch and read, learned from what you do (no ratings needed, like a video site's feed).

Signals, per item, weighted by how recent they are (half-life 120 days):
  + finished it, watched most of it, came back to it, read a good part of it
  − opened it and left almost at once, or dismissed it ("Not interested")
From these the model learns:
  channels and sites   how much you engage with each one (shrunk toward neutral until there's enough evidence)
  length               which lengths you tend to finish
  topics               the words of what you enjoyed (topic words, not grammar words), compared with each candidate
Each suggestion's rank is multiplied by exp(0.55·channel + 0.3·length + 0.6·topic), kept between ×0.45 and ×2.2.
Channels you've never tried get a small bonus, so new ones keep turning up.
"""

from __future__ import annotations

import math
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Connection, text

from app.services.catalog import name_key
from app.timeutil import from_iso, utc_now

HALF_LIFE_DAYS = 120.0
CHANNEL_SHRINK, LENGTH_SHRINK = 1.5, 3.0
WEIGHTS = {"channel": 0.55, "length": 0.3, "topic": 0.6}
NOVELTY = 0.05
CLIP = (0.45, 2.2)
TOPIC_RANKS = (400, 40000)  # frequency ranks that carry topics (common grammar words and rare names left out)
TOPIC_TERMS = 80  # strongest topic words kept per item
MAX_DOC_SHARE = 0.3
FILLERS = ("ähm", "äh", "hm", "mhm", "okay", "ok", "genau", "eh", "este", "pues", "bueno", "vale", "えー", "えっと", "あの", "まあ", "うん")
# topics are carried by nouns, verbs and adjectives; names, fillers (ähm), numbers and the like are left out
TOPIC_FILTER = "l.is_proper = 0 AND l.pos IN ('NOUN', 'VERB', 'ADJ', 'ADV', '')"
CACHE_SECONDS = 90.0
WATCH_TYPES = {"youtube", "video", "audio", "podcast_episode"}


def length_bucket(item_type: str, duration_sec: int | None, word_count: int | None) -> str | None:
    if item_type in WATCH_TYPES:
        if not duration_sec:
            return None
        minutes = duration_sec / 60
        for limit, name in ((6, "under 6 min"), (12, "6–12 min"), (20, "12–20 min"), (35, "20–35 min")):
            if minutes < limit:
                return name
        return "over 35 min"
    if not word_count:
        return None
    for limit, name in ((400, "short (under 400 words)"), (1000, "medium (400–1,000 words)"), (2500, "long (1,000–2,500 words)")):
        if word_count < limit:
            return name
    return "very long (2,500+ words)"


def owner_of(item_type: str, creator: str | None, site: str | None) -> str | None:
    """The channel (videos) or site (reading) an item belongs to."""
    return (creator if item_type in WATCH_TYPES else site or creator) or None


def engagement(item: dict[str, Any]) -> float | None:
    """From −1 (didn't like it) to +1.3 (watched all of it, came back)."""
    if item["dismissed_by_you"]:
        return -1.0
    seconds = item["seconds"] or 0
    if item["type"] in WATCH_TYPES:
        if not seconds and not item["opened"]:
            return None
        duration = item["duration_sec"] or 600
        share = seconds / duration
        e = 1.0 if share >= 0.6 or item["status"] == "finished" else 0.5 if share >= 0.3 else 0.0 if share >= 0.1 else -0.4
        if item["sessions"] >= 2 and share >= 0.3:
            e += 0.3
        return e
    progress = item["progress"] or 0
    if item["status"] == "finished" or progress >= 0.6:
        return 1.0
    if seconds >= 300 or progress >= 0.25:
        return 0.5
    if item["opened"] and seconds < 60:
        return -0.3
    return 0.0 if item["opened"] else None


@dataclass
class TasteProfile:
    lang: str
    channels: dict[str, float] = field(default_factory=dict)
    channel_names: dict[str, str] = field(default_factory=dict)
    channel_evidence: dict[str, float] = field(default_factory=dict)
    lengths: dict[str, float] = field(default_factory=dict)
    topics: dict[int, float] = field(default_factory=dict)
    topic_words: list[str] = field(default_factory=list)
    idf: dict[int, float] = field(default_factory=dict)
    signals: int = 0

    def channel_affinity(self, name: str | None) -> float:
        return self.channels.get(name_key(name), 0.0)

    def knows_channel(self, name: str | None) -> bool:
        return name_key(name) in self.channels

    def similarity(self, vector: dict[int, float] | None) -> float:
        if not vector or not self.topics:
            return 0.0
        return sum(w * self.topics.get(k, 0.0) for k, w in vector.items())

    def multiplier(self, item: dict[str, Any], vector: dict[int, float] | None = None) -> tuple[float, list[str]]:
        owner = owner_of(item["type"], item.get("creator"), item.get("site"))
        channel = self.channel_affinity(owner)
        bucket = length_bucket(item["type"], item.get("duration_sec"), item.get("word_count"))
        length = self.lengths.get(bucket, 0.0) if bucket else 0.0
        topic = max(-0.5, min(0.8, self.similarity(vector)))
        novelty = NOVELTY if owner and self.signals >= 5 and not self.knows_channel(owner) else 0.0
        raw = WEIGHTS["channel"] * channel + WEIGHTS["length"] * length + WEIGHTS["topic"] * topic + novelty
        factor = max(CLIP[0], min(CLIP[1], math.exp(raw)))
        reasons = []
        if channel >= 0.35 and owner:
            reasons.append(f"you often {'watch' if item['type'] in WATCH_TYPES else 'read'} {owner}")
        if topic >= 0.25:
            reasons.append("similar to things you enjoyed")
        if length >= 0.3 and bucket:
            reasons.append(f"a length you usually finish ({bucket})")
        if novelty and not reasons:
            reasons.append(f"new {'channel' if item['type'] in WATCH_TYPES else 'source'} for you")
        return factor, reasons

    def summary(self, limit: int = 8) -> dict[str, Any]:
        liked = sorted(((k, v) for k, v in self.channels.items() if v > 0.05), key=lambda kv: -kv[1])[:limit]
        disliked = sorted(((k, v) for k, v in self.channels.items() if v < -0.05), key=lambda kv: kv[1])[:4]
        lengths = sorted(((k, v) for k, v in self.lengths.items() if v > 0.05), key=lambda kv: -kv[1])[:3]
        return {
            "language": self.lang,
            "signals": self.signals,
            "channels": [{"name": self.channel_names.get(k, k), "affinity": round(v, 2), "evidence": round(self.channel_evidence.get(k, 0), 1)} for k, v in liked],
            "less_of": [{"name": self.channel_names.get(k, k), "affinity": round(v, 2)} for k, v in disliked],
            "lengths": [{"bucket": k, "affinity": round(v, 2)} for k, v in lengths],
            "topics": self.topic_words[:12],
        }


# ------------------------------------------------------------------ building


def _signals(conn: Connection, lang: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            "SELECT ci.id, ci.type, ci.creator, json_extract(ci.metadata_json, '$.site'), ci.duration_sec, ci.word_count, "
            "ci.status, ci.progress, COALESCE(json_extract(ci.metadata_json, '$.dismissed_by_you'), 0), ci.last_opened_at, "
            "COALESCE(SUM(s.active_seconds), 0), COUNT(s.id), MAX(s.started_at), "
            "COALESCE(json_extract(ci.metadata_json, '$.dismissed_at'), ci.last_opened_at, ci.added_at) "
            "FROM content_items ci LEFT JOIN activity_sessions s ON s.content_item_id = ci.id "
            "WHERE ci.language_code = :l AND (s.id IS NOT NULL OR ci.last_opened_at IS NOT NULL "
            "OR json_extract(ci.metadata_json, '$.dismissed_by_you') = 1) GROUP BY ci.id"
        ),
        {"l": lang},
    ).all()
    keys = ("id", "type", "creator", "site", "duration_sec", "word_count", "status", "progress", "dismissed_by_you", "last_opened_at",
            "seconds", "sessions", "last_session", "other_time")
    out = []
    for row in rows:
        item = dict(zip(keys, row))
        item["opened"] = item["last_opened_at"] is not None
        out.append(item)
    return out


def _idf(conn: Connection, lang: str) -> dict[int, float]:
    rows = conn.execute(
        text(
            "SELECT cl.lexeme_id, COUNT(*) FROM content_lemmas cl JOIN content_items ci ON ci.id = cl.content_item_id "
            "JOIN lexemes l ON l.id = cl.lexeme_id WHERE ci.language_code = :l AND l.freq_rank BETWEEN :a AND :b "
            f"AND {TOPIC_FILTER} GROUP BY cl.lexeme_id"
        ),
        {"l": lang, "a": TOPIC_RANKS[0], "b": TOPIC_RANKS[1]},
    ).all()
    docs = conn.execute(
        text("SELECT COUNT(DISTINCT cl.content_item_id) FROM content_lemmas cl JOIN content_items ci ON ci.id = cl.content_item_id WHERE ci.language_code = :l"),
        {"l": lang},
    ).scalar() or 1
    fillers = {
        r[0]
        for r in conn.execute(
            text(f"SELECT id FROM lexemes WHERE language_code = :l AND lower(lemma) IN ({', '.join(repr(w) for w in FILLERS)})"),
            {"l": lang},
        ).all()
    }
    # a word in most of your videos (a presenter's name, a filler) says nothing about the topic
    return {lex: math.log((docs + 1) / (df + 1)) + 1 for lex, df in rows if df / docs <= MAX_DOC_SHARE and lex not in fillers}


def vectors(conn: Connection, item_ids: list[int], idf: dict[int, float]) -> dict[int, dict[int, float]]:
    """Unit-length topic vectors (tf·idf over topic words) for these items."""
    raw: dict[int, list[tuple[int, float]]] = defaultdict(list)
    for start in range(0, len(item_ids), 400):
        chunk = item_ids[start : start + 400]
        rows = conn.execute(
            text(
                f"SELECT cl.content_item_id, cl.lexeme_id, cl.count FROM content_lemmas cl JOIN lexemes l ON l.id = cl.lexeme_id "
                f"WHERE cl.content_item_id IN ({','.join(str(int(i)) for i in chunk)}) AND l.freq_rank BETWEEN :a AND :b "
                f"AND {TOPIC_FILTER}"
            ),
            {"a": TOPIC_RANKS[0], "b": TOPIC_RANKS[1]},
        ).all()
        for item_id, lex, count in rows:
            if lex in idf:
                raw[item_id].append((lex, (1 + math.log(count)) * idf[lex]))
    out = {}
    for item_id, terms in raw.items():
        terms.sort(key=lambda t: -t[1])
        terms = terms[:TOPIC_TERMS]
        norm = math.sqrt(sum(w * w for _, w in terms)) or 1.0
        out[item_id] = {lex: w / norm for lex, w in terms}
    return out


def build(conn: Connection, lang: str) -> TasteProfile:
    profile = TasteProfile(lang)
    now = utc_now()
    signals = _signals(conn, lang)
    channel_sum: dict[str, float] = defaultdict(float)
    channel_weight: dict[str, float] = defaultdict(float)
    length_sum: dict[str, float] = defaultdict(float)
    length_weight: dict[str, float] = defaultdict(float)
    weighted: list[tuple[int, float]] = []
    for item in signals:
        e = engagement(item)
        if e is None:
            continue
        when = item["last_session"] or item["other_time"]
        age = max(0.0, (now - from_iso(when)).total_seconds() / 86400) if when else 0.0
        w = 0.5 ** (age / HALF_LIFE_DAYS)
        profile.signals += 1
        owner = owner_of(item["type"], item["creator"], item["site"])
        if owner:
            key = name_key(owner)
            profile.channel_names.setdefault(key, owner)
            channel_sum[key] += w * e
            channel_weight[key] += w
        bucket = length_bucket(item["type"], item["duration_sec"], item["word_count"])
        if bucket:
            length_sum[bucket] += w * e
            length_weight[bucket] += w
        if e != 0:
            weighted.append((item["id"], w * e))
    profile.channels = {k: max(-1.0, min(1.0, channel_sum[k] / (channel_weight[k] + CHANNEL_SHRINK))) for k in channel_sum}
    profile.channel_evidence = dict(channel_weight)
    profile.lengths = {k: max(-1.0, min(1.0, length_sum[k] / (length_weight[k] + LENGTH_SHRINK))) for k in length_sum}

    # topics: the weighted sum of the topic vectors of what you engaged with
    profile.idf = _idf(conn, lang)
    item_vectors = vectors(conn, [i for i, _ in weighted], profile.idf)
    topics: dict[int, float] = defaultdict(float)
    for item_id, weight in weighted:
        for lex, value in item_vectors.get(item_id, {}).items():
            topics[lex] += weight * value
    norm = math.sqrt(sum(v * v for v in topics.values())) or 1.0
    profile.topics = {k: v / norm for k, v in topics.items() if abs(v / norm) >= 0.005}
    top = sorted((k for k, v in profile.topics.items() if v > 0), key=lambda k: -profile.topics[k])[:25]
    if top:
        names = dict(conn.execute(text(f"SELECT id, lemma FROM lexemes WHERE id IN ({','.join(str(k) for k in top)})")).all())
        seen: set[str] = set()
        for k in top:
            word = names.get(k)
            if word and word.casefold() not in seen and word.isalpha():
                seen.add(word.casefold())
                profile.topic_words.append(word)
    return profile


# ------------------------------------------------------------------ cache

_CACHE: dict[str, tuple[float, TasteProfile]] = {}
_VECTORS: dict[int, dict[int, float]] = {}


def profile(conn: Connection, lang: str) -> TasteProfile:
    cached = _CACHE.get(lang)
    if cached and time.monotonic() - cached[0] < CACHE_SECONDS:
        return cached[1]
    built = build(conn, lang)
    _CACHE[lang] = (time.monotonic(), built)
    return built


def item_vectors(conn: Connection, item_ids: list[int], idf: dict[int, float]) -> dict[int, dict[int, float]]:
    missing = [i for i in item_ids if i not in _VECTORS]
    if missing:
        found = vectors(conn, missing, idf)
        for item_id in missing:
            _VECTORS[item_id] = found.get(item_id, {})
        if len(_VECTORS) > 20000:
            _VECTORS.clear()
    return {i: _VECTORS.get(i, {}) for i in item_ids}


def invalidate(lang: str | None = None, item_id: int | None = None) -> None:
    if lang is None:
        _CACHE.clear()
    else:
        _CACHE.pop(lang, None)
    if item_id is not None:
        _VECTORS.pop(item_id, None)


def explain(conn: Connection, lang: str) -> dict[str, Any]:
    return profile(conn, lang).summary()
