"""Listening check by dictation: hear a sentence (browser voice), type what you heard.

Adaptive over levels A1 → C1: start at B1, go up after a clean sentence (≥ 85 % of words),
down after a poor one (< 60 %). Ten sentences. The band is the highest level where your
average is at least 75 % (with at least two sentences heard there).

Scoring is about hearing, not spelling: case, punctuation and accents are ignored. Japanese is
compared by kana reading, so typing かな instead of 漢字 is not penalised.
"""

from __future__ import annotations

import json
import random
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy import Connection, text

from app.level.dictation_sentences import LEVELS, SENTENCES
from app.timeutil import to_iso, utc_now

ITEMS = 10
START_LEVEL = 2  # B1
UP, DOWN, PASS = 0.85, 0.60, 0.75
MAX_PLAYS = 3


class DictationError(ValueError):
    pass


def available(lang: str) -> bool:
    return lang in SENTENCES


def _fold(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).lower().replace("ß", "ss")
    value = "".join(c for c in unicodedata.normalize("NFD", value) if unicodedata.category(c) != "Mn")
    return re.sub(r"[^\w\s]", " ", value)


def _kana(value: str) -> str:
    from app.languages import get_pack
    from app.languages.ja import to_hiragana

    tagger = get_pack("ja").tagger  # reuse the loaded MeCab tagger
    parts = []
    for word in tagger(unicodedata.normalize("NFKC", value)):
        if word.feature.pos1 in {"補助記号", "記号", "空白"}:
            continue
        parts.append(to_hiragana(word.feature.kana or word.surface))
    return "".join(parts)


def score(lang: str, expected: str, typed: str) -> float:
    if lang == "ja":
        want, got = _kana(expected), _kana(typed)
        if not want:
            return 0.0
        matched = sum(block.size for block in SequenceMatcher(None, want, got, autojunk=False).get_matching_blocks())
        return round(matched / len(want), 3)
    want, got = _fold(expected).split(), _fold(typed).split()
    if not want:
        return 0.0
    matched = sum(block.size for block in SequenceMatcher(None, want, got, autojunk=False).get_matching_blocks())
    return round(matched / len(want), 3)


def _items(conn: Connection, assessment_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        text("SELECT id, seq, prompt_json, response, score FROM assessment_items WHERE assessment_id = :a ORDER BY seq"),
        {"a": assessment_id},
    ).all()
    return [{"id": r[0], "seq": r[1], "prompt": json.loads(r[2]), "response": r[3], "score": r[4]} for r in rows]


def _new_item(conn: Connection, assessment_id: int, lang: str, level_index: int, used: set[str], seq: int) -> dict[str, Any]:
    rng = random.Random(assessment_id * 1009 + seq)
    level = LEVELS[level_index]
    options = [s for s in SENTENCES[lang][level] if s not in used] or SENTENCES[lang][level]
    sentence = rng.choice(options)
    item_id = conn.execute(
        text(
            "INSERT INTO assessment_items (assessment_id, seq, item_type, difficulty, prompt_json) "
            "VALUES (:a, :seq, 'dictation', :d, :p)"
        ),
        {"a": assessment_id, "seq": seq, "d": level_index, "p": json.dumps({"level": level, "sentence": sentence}, ensure_ascii=False)},
    ).lastrowid
    # The client needs the sentence to speak it with the browser's voice; the UI never displays it before answering.
    return {"id": item_id, "seq": seq, "level": level, "speak": sentence, "total": ITEMS, "max_plays": MAX_PLAYS}


def start(conn: Connection, lang: str) -> dict[str, Any]:
    if not available(lang):
        raise DictationError("The listening check is not available for this language yet.")
    assessment_id = conn.execute(
        text("INSERT INTO assessments (language_code, skill, method) VALUES (:l, 'listening', 'dictation')"), {"l": lang}
    ).lastrowid
    return {"assessment_id": assessment_id, "done": False, "item": _new_item(conn, assessment_id, lang, START_LEVEL, set(), 1)}


def answer(conn: Connection, assessment_id: int, item_id: int, typed: str, plays: int) -> dict[str, Any]:
    row = conn.execute(
        text("SELECT language_code, status, method FROM assessments WHERE id = :id"), {"id": assessment_id}
    ).first()
    if not row or row[2] != "dictation":
        raise DictationError("no such listening check")
    if row[1] != "in_progress":
        raise DictationError("this listening check is already finished")
    lang = row[0]
    items = _items(conn, assessment_id)
    item = next((i for i in items if i["id"] == item_id), None)
    if not item or item["response"] is not None:
        raise DictationError("this sentence was already answered" if item else "no such sentence")
    accuracy = score(lang, item["prompt"]["sentence"], typed[:500])
    conn.execute(
        text("UPDATE assessment_items SET response = :r, score = :s WHERE id = :id"),
        {"r": json.dumps({"typed": typed[:500], "plays": min(plays, MAX_PLAYS)}, ensure_ascii=False), "s": accuracy, "id": item_id},
    )
    feedback = {"sentence": item["prompt"]["sentence"], "accuracy": accuracy, "level": item["prompt"]["level"]}
    answered = [i for i in items if i["response"] is not None] + [{**item, "score": accuracy}]
    if len(answered) >= ITEMS:
        return {"done": True, "feedback": feedback, "result": _finish(conn, assessment_id, lang, answered)}
    level_index = LEVELS.index(item["prompt"]["level"])
    if accuracy >= UP:
        level_index = min(level_index + 1, len(LEVELS) - 1)
    elif accuracy < DOWN:
        level_index = max(level_index - 1, 0)
    used = {i["prompt"]["sentence"] for i in items}
    nxt = _new_item(conn, assessment_id, lang, level_index, used, len(items) + 1)
    return {"done": False, "feedback": feedback, "item": nxt}


def _finish(conn: Connection, assessment_id: int, lang: str, answered: list[dict[str, Any]]) -> dict[str, Any]:
    by_level: dict[str, list[float]] = {level: [] for level in LEVELS}
    for item in answered:
        by_level[item["prompt"]["level"]].append(item["score"])
    averages = {level: round(sum(v) / len(v), 3) for level, v in by_level.items() if v}
    passed = [level for level in LEVELS if len(by_level[level]) >= 2 and averages[level] >= PASS]
    band = passed[-1] if passed else ("A1" if averages.get("A1", 0) >= 0.5 else "below A1")
    index = LEVELS.index(band) if band in LEVELS else -1
    above = LEVELS[index + 1] if 0 <= index + 1 < len(LEVELS) else None
    band_high = above if above and averages.get(above, 0) >= DOWN else band
    band_low = band if band not in LEVELS or averages.get(band, 0) >= UP else (LEVELS[index - 1] if index > 0 else band)
    overall = round(sum(i["score"] for i in answered) / len(answered), 3)
    result = {"band": band, "band_low": band_low, "band_high": band_high, "averages": averages, "overall": overall, "sentences": len(answered)}
    now = to_iso(utc_now())
    conn.execute(
        text("UPDATE assessments SET status = 'done', raw_score = :raw, result_json = :r, finished_at = :now WHERE id = :id"),
        {"raw": overall, "r": json.dumps(result), "now": now, "id": assessment_id},
    )
    conn.execute(
        text(
            "INSERT INTO skill_estimates (language_code, skill, theta, theta_se, band, band_low, band_high, last_tested_at, "
            "updated_at) VALUES (:l, 'listening', :t, 0.6, :b, :bl, :bh, :now, :now) ON CONFLICT(language_code, skill) "
            "DO UPDATE SET theta = excluded.theta, theta_se = excluded.theta_se, band = excluded.band, "
            "band_low = excluded.band_low, band_high = excluded.band_high, last_tested_at = excluded.last_tested_at, "
            "updated_at = excluded.updated_at"
        ),
        {"l": lang, "t": index + 1, "b": band, "bl": band_low, "bh": band_high, "now": now},
    )
    return result
