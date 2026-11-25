"""Listening check by dictation: hear a sentence (browser voice), type what you heard.

The same flow runs the speaking check (elicited imitation): hear a sentence, say it back, and the browser's speech
recogniser's transcript is scored the same way. Repeating longer sentences correctly needs you to understand and
rebuild them, which is why imitation tracks oral proficiency well. It is stored as skill 'speaking'.

Adaptive over levels A1 → C1: start at B1, go up after a clean sentence (≥ 85 % of words),
down after a poor one (< 60 %). Ten sentences. The band is the highest level where your
average is at least 75 % (with at least two sentences heard there).

Scoring is about hearing, not spelling: case, punctuation and accents are ignored. Japanese is
compared by kana reading, so typing かな instead of 漢字 is not penalised.
"""

from __future__ import annotations

import json
import random
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

KINDS = {
    "dictation": {"skill": "listening", "method": "dictation", "item": "dictation", "name": "listening check"},
    "imitation": {"skill": "speaking", "method": "elicited_imitation", "item": "imitation", "name": "speaking check"},
}


class DictationError(ValueError):
    pass


def available(lang: str) -> bool:
    return lang in SENTENCES


def _fold(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).lower().replace("ß", "ss")
    value = "".join(c for c in unicodedata.normalize("NFD", value) if unicodedata.category(c) != "Mn")
    # punctuation and symbols become spaces; vowel signs of Hindi and Bengali (Mc) stay part of their word
    return "".join(" " if unicodedata.category(c)[0] in "PS" else c for c in value)


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
    from app.languages.registry import get

    spec = get(lang)
    if spec and not spec.spaced:  # Chinese: compare character by character
        want_chars, got_chars = _fold(expected).replace(" ", ""), _fold(typed).replace(" ", "")
        if not want_chars:
            return 0.0
        matched = sum(b.size for b in SequenceMatcher(None, want_chars, got_chars, autojunk=False).get_matching_blocks())
        return round(matched / len(want_chars), 3)
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


def _new_item(
    conn: Connection, assessment_id: int, lang: str, level_index: int, used: set[str], seq: int, kind: str = "dictation"
) -> dict[str, Any]:
    rng = random.Random(assessment_id * 1009 + seq)
    level = LEVELS[level_index]
    options = [s for s in SENTENCES[lang][level] if s not in used] or SENTENCES[lang][level]
    sentence = rng.choice(options)
    item_id = conn.execute(
        text(
            "INSERT INTO assessment_items (assessment_id, seq, item_type, difficulty, prompt_json) "
            "VALUES (:a, :seq, :kind, :d, :p)"
        ),
        {"a": assessment_id, "seq": seq, "kind": KINDS[kind]["item"], "d": level_index, "p": json.dumps({"level": level, "sentence": sentence}, ensure_ascii=False)},
    ).lastrowid
    # The client needs the sentence to speak it with the browser's voice; the UI never displays it before answering.
    return {"id": item_id, "seq": seq, "level": level, "speak": sentence, "total": ITEMS, "max_plays": MAX_PLAYS}


def start(conn: Connection, lang: str, kind: str = "dictation") -> dict[str, Any]:
    spec = KINDS[kind]
    if not available(lang):
        raise DictationError(f"The {spec['name']} is not available for this language yet.")
    assessment_id = conn.execute(
        text("INSERT INTO assessments (language_code, skill, method) VALUES (:l, :skill, :method)"),
        {"l": lang, "skill": spec["skill"], "method": spec["method"]},
    ).lastrowid
    first = _new_item(conn, assessment_id, lang, START_LEVEL, set(), 1, kind)
    return {"assessment_id": assessment_id, "done": False, "item": first}


def answer(conn: Connection, assessment_id: int, item_id: int, typed: str, plays: int) -> dict[str, Any]:
    row = conn.execute(
        text("SELECT language_code, status, method FROM assessments WHERE id = :id"), {"id": assessment_id}
    ).first()
    kind = next((k for k, spec in KINDS.items() if row and spec["method"] == row[2]), None)
    if not row or kind is None:
        raise DictationError("no such check")
    if row[1] != "in_progress":
        raise DictationError(f"this {KINDS[kind]['name']} is already finished")
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
        return {"done": True, "feedback": feedback, "result": _finish(conn, assessment_id, lang, answered, KINDS[kind]["skill"])}
    level_index = LEVELS.index(item["prompt"]["level"])
    if accuracy >= UP:
        level_index = min(level_index + 1, len(LEVELS) - 1)
    elif accuracy < DOWN:
        level_index = max(level_index - 1, 0)
    used = {i["prompt"]["sentence"] for i in items}
    nxt = _new_item(conn, assessment_id, lang, level_index, used, len(items) + 1, kind)
    return {"done": False, "feedback": feedback, "item": nxt}


def _finish(
    conn: Connection, assessment_id: int, lang: str, answered: list[dict[str, Any]], skill: str = "listening"
) -> dict[str, Any]:
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
            "updated_at) VALUES (:l, :skill, :t, 0.6, :b, :bl, :bh, :now, :now) ON CONFLICT(language_code, skill) "
            "DO UPDATE SET theta = excluded.theta, theta_se = excluded.theta_se, band = excluded.band, "
            "band_low = excluded.band_low, band_high = excluded.band_high, last_tested_at = excluded.last_tested_at, "
            "updated_at = excluded.updated_at"
        ),
        {"l": lang, "skill": skill, "t": index + 1, "b": band, "bl": band_low, "bh": band_high, "now": now},
    )
    return result
