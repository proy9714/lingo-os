"""How well you remember each word you're learning, learned from what you watch, read and look up. No flashcards.

Every word you're learning (or have as familiar or known) has a *stability* S: about how many days you'd still
recognise it without meeting it again. How likely you are to recognise it now is

    R = 2 ^ (-days since you last met it / S)         (1 right after meeting it, ½ after S days, ¼ after 2S…)

What changes S, replayed in order from the moment the word got its current status:

  meeting it   a day on which you met the word in a video, audio or article you actually watched or read (not the
               whole item: the share you got through), without looking it up:
                   S ← S × (1 + g · w · (1 + b·(1 − R)) / (1 + D))
               w   how much you met it that day, saturating: 1 − e^(−n/3) for n weighted meetings (the third
                   meeting in one sitting adds little; meeting it again on another day adds a lot)
               R   how likely you were to recognise it just before: meeting a word as it starts to fade
                   strengthens it most (the spacing effect), meeting it again the next morning a little
               D   difficulty: rarer words (far beyond your vocabulary frontier) and words you keep looking up grow
                   more slowly
  looking it up  you didn't recognise it: S ← S × lapse, and the word gets a little harder (D + 0.15)

Statuses follow S, with a gap between moving up and moving down so a word doesn't flicker:

  learning → familiar   S ≥ 5 days, met on 3+ days, R ≥ 0.5 now, no lookup in the last 2 days
  familiar → known      S ≥ 25 days, met on 3+ days spread over 7+ days, no lookup since it became familiar
  known → familiar      S fell below 12.5 days (looked up twice or more since)        [only automatic statuses,
  familiar → learning   S fell below 2.5 days                                           or yours after 30 days
                                                                                        and three lookups]

The thresholds scale with your pace setting (cautious ×1.4, balanced ×1, eager ×0.7), and g and lapse are fitted to
you (fit()): every lookup is a moment the model said "probably remembers" or not, every day you met a word and looked
up others but not this one is a quiet "still remembers", and every automatic move you undid is a clear "too early".
The values that predict your own history best (pulled toward the defaults until there's enough of it) are kept in
the settings as word_model.<lang>; until then the defaults apply.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Connection, text

from app.db import settings_store
from app.timeutil import from_iso, local_day, to_iso, utc_now

COUNTED_TYPES = ("youtube", "video", "audio", "podcast_episode", "article", "text")
READING_WPM = 150.0  # to tell how much of an article a session covered

DEFAULTS = {"g": 1.0, "b": 1.5, "lapse": 0.45}
ANCHOR_S = {"learning": 1.0, "familiar": 10.0, "known": 60.0, "seen": 0.5}
THRESHOLDS = {"familiar": 5.0, "known": 25.0}
PACE = {"cautious": 1.4, "balanced": 1.0, "eager": 0.7}
MIN_DAYS = {"familiar": 3, "known": 3}
RECENT_ENOUGH = 0.5  # met within about one stability span: not a word you last saw months ago
KNOWN_SPAN_DAYS = 7
QUIET_DAYS = 2
MANUAL_GRACE_DAYS = 30
MANUAL_LAPSES_TO_MOVE = 3
S_MIN, S_MAX = 0.25, 3650.0
FIT_GRID = {"g": (0.5, 0.7, 1.0, 1.4, 2.0, 2.8), "lapse": (0.3, 0.45, 0.6)}
FIT_SHRINK = 8.0  # how many labels' worth of weight the defaults carry
FIT_EVERY = timedelta(days=1)
SOURCES = ("manual", "auto", "test", "sync")


@dataclass
class WordMemory:
    lexeme_id: int
    lemma: str
    reading: str
    status: str
    source: str  # who set the current status: manual / auto / test / sync
    since: datetime  # when it got that status
    rank: int | None
    stability: float = 1.0
    difficulty: float = 0.0
    last_met: datetime | None = None
    evidence_days: list[str] = field(default_factory=list)  # local days met without a lookup
    times: float = 0.0  # weighted meetings
    lapses: int = 0  # lookups since `since`
    last_lookup: datetime | None = None

    def recall(self, at: datetime | None = None) -> float:
        last = self.last_met or self.since
        days = max(0.0, ((at or utc_now()) - last).total_seconds() / 86400)
        return 2.0 ** (-days / max(self.stability, S_MIN))


# ------------------------------------------------------------------ evidence


def _profile_r50(conn: Connection, lang: str) -> float:
    from app.engine.profile import get_profile

    profile = get_profile(conn, lang)
    return float(profile["r50"]) if profile else 2000.0


def difficulty_for(rank: int | None, r50: float) -> float:
    """0 for words around or below your frontier, up to 0.5 for words far beyond it (or not in the frequency list)."""
    if rank is None:
        return 0.3
    return min(0.5, max(0.0, 0.15 * math.log2(max(rank, 1) / max(r50, 1.0))))


def _status_sources(conn: Connection, ids: list[int]) -> dict[int, str]:
    """Who set each word's current status, from its latest status event."""
    if not ids:
        return {}
    rows = conn.execute(
        text(
            "SELECT e.lexeme_id, e.event, e.value FROM word_events e JOIN ("
            " SELECT lexeme_id, MAX(id) AS id FROM word_events WHERE event IN ('status_change', 'save', 'test_known', 'test_unknown') "
            f" AND lexeme_id IN ({','.join(map(str, ids))}) GROUP BY lexeme_id) last ON last.id = e.id"
        )
    ).all()
    out = {}
    for lexeme_id, event, value in rows:
        value = value or ""
        if "(automatic" in value:
            out[lexeme_id] = "auto"
        elif event.startswith("test_"):
            out[lexeme_id] = "test"
        elif "(phone" in value:
            out[lexeme_id] = "sync"
        else:
            out[lexeme_id] = "manual"
    return out


def _meetings(conn: Connection, ids: list[int], since: str) -> dict[int, list[tuple[datetime, float]]]:
    """Per word: (when, weighted times met) for each session in content you watched or read containing it.

    A session counts the share of the item it covered (60 s of a 20-minute video meets a word a twentieth as often
    as watching it all); sessions under a minute don't count, and whole books and manga volumes don't (their word
    lists cover every page, not the pages you read)."""
    if not ids:
        return {}
    types = ", ".join(f"'{t}'" for t in COUNTED_TYPES)
    rows = conn.execute(
        text(
            "SELECT cl.lexeme_id, s.started_at, cl.count, s.active_seconds, ci.duration_sec, ci.word_count FROM content_lemmas cl "
            "JOIN content_items ci ON ci.id = cl.content_item_id JOIN activity_sessions s ON s.content_item_id = ci.id "
            f"WHERE cl.lexeme_id IN ({','.join(map(str, ids))}) AND ci.type IN ({types}) AND s.is_baseline = 0 "
            "AND s.active_seconds >= 60 AND s.started_at > :since"
        ),
        {"since": since},
    ).all()
    out: dict[int, list[tuple[datetime, float]]] = defaultdict(list)
    for lexeme_id, started, count, seconds, duration, words in rows:
        if duration:
            share = min(1.0, seconds / duration)
        elif words:
            share = min(1.0, seconds / max(60.0, words / READING_WPM * 60))
        else:
            share = 1.0  # length unknown: count it as watched
        out[lexeme_id].append((from_iso(started), float(count or 1) * share))
    return out


def _lookups(conn: Connection, ids: list[int], since: str) -> dict[int, list[datetime]]:
    if not ids:
        return {}
    rows = conn.execute(
        text(
            f"SELECT lexeme_id, created_at FROM word_events WHERE event = 'lookup' AND lexeme_id IN ({','.join(map(str, ids))}) "
            "AND created_at > :since"
        ),
        {"since": since},
    ).all()
    out: dict[int, list[datetime]] = defaultdict(list)
    for lexeme_id, at in rows:
        out[lexeme_id].append(from_iso(at))
    return out


def _lookup_days(conn: Connection, lang: str, since: str) -> set[str]:
    """Days you looked anything up in this language: you were reading or listening attentively that day."""
    rows = conn.execute(
        text(
            "SELECT e.created_at FROM word_events e JOIN lexemes l ON l.id = e.lexeme_id "
            "WHERE e.event = 'lookup' AND l.language_code = :l AND e.created_at > :since"
        ),
        {"l": lang, "since": since},
    ).all()
    return {local_day(r[0]).isoformat() for r in rows}


# ------------------------------------------------------------------ the model


def _replay(word: WordMemory, meetings: list[tuple[datetime, float]], lookups: list[datetime], params: dict[str, float],
            labels: list[tuple[float, bool, float]] | None = None, attentive_days: set[str] | None = None) -> WordMemory:
    """Run a word's history since it got its status through the model. With `labels`, record (predicted R, was it
    remembered, weight) at each piece of evidence, for fitting."""
    events: list[tuple[datetime, str, float]] = [(at, "meet", n) for at, n in meetings if at > word.since]
    events += [(at, "lookup", 0.0) for at in lookups if at > word.since]
    events.sort(key=lambda e: e[0])
    by_day: dict[str, list[tuple[datetime, str, float]]] = defaultdict(list)
    for event in events:
        by_day[local_day(to_iso(event[0])).isoformat()].append(event)
    for day in sorted(by_day):
        today = by_day[day]
        first = today[0][0]
        recall = word.recall(first)
        looked = [at for at, kind, _ in today if kind == "lookup"]
        if looked:
            if labels is not None:
                labels.append((recall, False, 1.0))
            word.stability = max(S_MIN, word.stability * params["lapse"])
            word.difficulty = min(1.5, word.difficulty + 0.15)
            word.lapses += 1
            word.last_lookup = max(looked)
            word.last_met = max(looked)
            continue
        weight = sum(n for _, kind, n in today if kind == "meet")
        if weight <= 0:
            continue
        if labels is not None and attentive_days is not None and day in attentive_days:
            labels.append((recall, True, 0.5))  # met it, looked other words up, not this one: likely remembered
        w = 1.0 - math.exp(-weight / 3.0)
        growth = params["g"] * w * (1.0 + params["b"] * (1.0 - recall)) / (1.0 + word.difficulty)
        word.stability = min(S_MAX, word.stability * (1.0 + growth))
        word.last_met = max(at for at, _, _ in today)
        word.evidence_days.append(day)
        word.times += weight
    return word


def params_for(conn: Connection, lang: str) -> dict[str, float]:
    stored = settings_store.get(conn, f"word_model.{lang}") or {}
    return {k: float(stored.get(k, v)) for k, v in DEFAULTS.items()}


def preferences(conn: Connection) -> dict[str, Any]:
    stored = settings_store.get(conn, "word_model.prefs") or {}
    pace = stored.get("pace") if stored.get("pace") in PACE else "balanced"
    return {"auto": bool(stored.get("auto", True)), "pace": pace}


def set_preferences(conn: Connection, auto: bool | None = None, pace: str | None = None) -> dict[str, Any]:
    prefs = preferences(conn)
    if auto is not None:
        prefs["auto"] = bool(auto)
    if pace is not None:
        if pace not in PACE:
            raise ValueError(f"pace is one of {', '.join(PACE)}")
        prefs["pace"] = pace
    settings_store.put(conn, "word_model.prefs", prefs)
    return prefs


def load_words(conn: Connection, lang: str, statuses: tuple[str, ...] = ("learning", "familiar", "known"),
               lexeme_ids: list[int] | None = None, params: dict[str, float] | None = None) -> list[WordMemory]:
    """Every word with one of these statuses (or these words), with its memory replayed up to now."""
    where = f"w.status IN ({', '.join(repr(s) for s in statuses)})"
    if lexeme_ids is not None:
        if not lexeme_ids:
            return []
        where = f"w.lexeme_id IN ({','.join(str(int(i)) for i in lexeme_ids)})"
    rows = conn.execute(
        text(
            "SELECT w.lexeme_id, l.lemma, l.reading, w.status, COALESCE(w.status_changed_at, w.first_seen_at), l.freq_rank, w.last_lookup_at "
            f"FROM user_words w JOIN lexemes l ON l.id = w.lexeme_id WHERE l.language_code = :l AND {where}"
        ),
        {"l": lang},
    ).all()
    if not rows:
        return []
    params = params or params_for(conn, lang)
    r50 = _profile_r50(conn, lang)
    ids = [r[0] for r in rows]
    earliest = min((r[4] for r in rows if r[4]), default="1970-01-01T00:00:00.000Z")
    sources = _status_sources(conn, ids)
    meetings = _meetings(conn, ids, earliest)
    lookups = _lookups(conn, ids, earliest)
    out = []
    for lexeme_id, lemma, reading, status, since, rank, last_lookup_at in rows:
        word = WordMemory(
            lexeme_id=lexeme_id, lemma=lemma, reading=reading or "", status=status, source=sources.get(lexeme_id, "manual"),
            since=from_iso(since or "1970-01-01T00:00:00.000Z"), rank=rank,
            stability=ANCHOR_S.get(status, 1.0), difficulty=difficulty_for(rank, r50),
        )
        _replay(word, meetings.get(lexeme_id, []), lookups.get(lexeme_id, []), params)
        if last_lookup_at:  # also a lookup the event log may not hold (older data, the phone)
            at = from_iso(last_lookup_at)
            word.last_lookup = max(word.last_lookup or at, at)
        out.append(word)
    return out


def recall_now(conn: Connection, lang: str) -> dict[int, float]:
    """How likely you are to recognise each word you're learning or have as familiar right now (0..1)."""
    now = utc_now()
    return {w.lexeme_id: round(w.recall(now), 4) for w in load_words(conn, lang, ("learning", "familiar"))}


def word_state(conn: Connection, lang: str, lexeme_ids: list[int]) -> dict[int, WordMemory]:
    return {w.lexeme_id: w for w in load_words(conn, lang, lexeme_ids=lexeme_ids)}


# ------------------------------------------------------------------ decisions


def next_move(word: WordMemory, prefs: dict[str, Any], now: datetime | None = None) -> str | None:
    """The status this word should move to now, or None to stay."""
    now = now or utc_now()
    scale = PACE[prefs["pace"]]
    days = sorted(set(word.evidence_days))
    quiet = word.last_lookup is None or (now - word.last_lookup) > timedelta(days=QUIET_DAYS)
    if word.status == "learning":
        if (
            word.stability >= THRESHOLDS["familiar"] * scale and len(days) >= MIN_DAYS["familiar"]
            and word.recall(now) >= RECENT_ENOUGH and quiet
        ):
            return "familiar"
        return None
    may_demote = word.source != "manual" or (
        now - word.since > timedelta(days=MANUAL_GRACE_DAYS) and word.lapses >= MANUAL_LAPSES_TO_MOVE
    )
    if word.status == "familiar":
        span = (from_iso(days[-1] + "T00:00:00Z") - from_iso(days[0] + "T00:00:00Z")).days if days else 0
        if (
            word.stability >= THRESHOLDS["known"] * scale and len(days) >= MIN_DAYS["known"]
            and span >= KNOWN_SPAN_DAYS and word.lapses == 0
        ):
            return "known"
        if may_demote and word.lapses >= 2 and word.stability < THRESHOLDS["familiar"] * scale * 0.5:
            return "learning"
        return None
    if word.status == "known":
        if may_demote and word.lapses >= 2 and word.stability < THRESHOLDS["known"] * scale * 0.5:
            return "familiar"
    return None


def explain(word: WordMemory, prefs: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    """Where a word stands, in plain words (no dates to review on: words come back through what you watch and read)."""
    now = now or utc_now()
    days = len(set(word.evidence_days))
    recall = word.recall(now)
    strength = "strong" if word.stability >= THRESHOLDS["known"] else "growing" if word.stability >= THRESHOLDS["familiar"] else "new"
    by = {"manual": "You set this yourself.", "auto": "Moved here automatically.", "test": "From your Level Lab test.",
          "sync": "Set on your phone."}[word.source]
    target = {"learning": "familiar", "familiar": "known"}.get(word.status)
    times = f"{word.lapses} time{'s' if word.lapses != 1 else ''}"
    if days:
        met = f"You've met it on {days} day{'s' if days != 1 else ''} since then"
        looked = f", and looked it up {times}." if word.lapses else " without looking it up."
    else:
        met = "You haven't met it in something you watched or read since then"
        looked = f", and looked it up {times}." if word.lapses else "."
    if word.status in ("learning", "familiar") and target:
        tail = (
            f" Keep meeting it on different days and it moves to {target} by itself."
            if prefs["auto"] else " Automatic moves are off (Words → settings)."
        )
    elif word.status == "known":
        tail = " If you find yourself looking it up again, it moves back to familiar."
    else:
        tail = ""
    return {
        "lexeme_id": word.lexeme_id,
        "status": word.status,
        "source": word.source,
        "since": to_iso(word.since),
        "days_met": days,
        "lookups": word.lapses,
        "strength": strength,
        "recall": round(recall, 2),
        "stability_days": round(word.stability, 1),
        "next": target,
        "message": f"{by} {met}{looked}{tail}".replace(" .", "."),
    }


# ------------------------------------------------------------------ fitting to you


def _log_loss(labels: list[tuple[float, bool, float]]) -> float:
    total = weight = 0.0
    for p, ok, w in labels:
        p = min(0.98, max(0.02, p))
        total -= w * (math.log(p) if ok else math.log(1.0 - p))
        weight += w
    return total / weight if weight else 0.0


def _labels_for(conn: Connection, lang: str, params: dict[str, float], words: list[WordMemory],
                meetings: dict[int, list[tuple[datetime, float]]], lookups: dict[int, list[datetime]],
                attentive: set[str], undone: dict[int, datetime]) -> list[tuple[float, bool, float]]:
    labels: list[tuple[float, bool, float]] = []
    r50 = _profile_r50(conn, lang)
    for base in words:
        word = WordMemory(
            lexeme_id=base.lexeme_id, lemma=base.lemma, reading=base.reading, status=base.status, source=base.source,
            since=base.since, rank=base.rank, stability=ANCHOR_S.get(base.status, 1.0), difficulty=difficulty_for(base.rank, r50),
        )
        _replay(word, meetings.get(word.lexeme_id, []), lookups.get(word.lexeme_id, []), params, labels, attentive)
        if word.lexeme_id in undone:  # an automatic move you took back: the model was too early
            labels.append((word.recall(undone[word.lexeme_id]), False, 2.0))
    return labels


def _undone_moves(conn: Connection, lang: str) -> dict[int, datetime]:
    """Words you moved back yourself within two weeks of an automatic move (latest such undo per word)."""
    rows = conn.execute(
        text(
            "SELECT a.lexeme_id, MIN(m.created_at) FROM word_events a JOIN word_events m ON m.lexeme_id = a.lexeme_id "
            "JOIN lexemes l ON l.id = a.lexeme_id "
            "WHERE l.language_code = :l AND a.event = 'status_change' AND a.value LIKE '%(automatic%' "
            "AND m.event IN ('status_change', 'save') AND m.value NOT LIKE '%(automatic%' AND m.created_at > a.created_at "
            "AND julianday(m.created_at) - julianday(a.created_at) <= 14 GROUP BY a.id"
        ),
        {"l": lang},
    ).all()
    return {lexeme_id: from_iso(at) for lexeme_id, at in rows}


def fit(conn: Connection, lang: str, *, force: bool = False) -> dict[str, Any]:
    """Fit growth and lapse to your own history (at most once a day unless forced); returns the stored model."""
    stored = settings_store.get(conn, f"word_model.{lang}") or {}
    if not force and stored.get("fitted_at") and utc_now() - from_iso(stored["fitted_at"]) < FIT_EVERY:
        return stored
    words = load_words(conn, lang, ("learning", "familiar", "known"), params=dict(DEFAULTS))
    earliest = min((to_iso(w.since) for w in words), default=to_iso(utc_now()))
    ids = [w.lexeme_id for w in words]
    meetings = _meetings(conn, ids, earliest)
    lookups = _lookups(conn, ids, earliest)
    attentive = _lookup_days(conn, lang, earliest)
    undone = _undone_moves(conn, lang)

    def score(params: dict[str, float]) -> tuple[float, int]:
        labels = _labels_for(conn, lang, params, words, meetings, lookups, attentive, undone)
        n = sum(w for _, _, w in labels)
        # shrinkage: the defaults count as FIT_SHRINK labels' worth of evidence
        prior = FIT_SHRINK * (math.log(params["g"] / DEFAULTS["g"]) ** 2 + math.log(params["lapse"] / DEFAULTS["lapse"]) ** 2)
        return (_log_loss(labels) * n + prior) / max(n, 1.0), len(labels)

    default_loss, count = score(dict(DEFAULTS))
    best, best_loss = dict(DEFAULTS), default_loss
    if count >= 10:  # too little history: keep the defaults
        for g in FIT_GRID["g"]:
            for lapse in FIT_GRID["lapse"]:
                params = {**DEFAULTS, "g": g, "lapse": lapse}
                loss, _ = score(params)
                if loss < best_loss - 1e-9:
                    best, best_loss = params, loss
    model = {
        **best,
        "fitted_at": to_iso(utc_now()),
        "labels": count,
        "loss_default": round(default_loss, 4),
        "loss_fitted": round(best_loss, 4),
        "words": len(words),
    }
    settings_store.put(conn, f"word_model.{lang}", model)
    return model
