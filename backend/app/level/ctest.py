"""C-test reading check: restore the missing second halves of words in four graded passages.

Rule: the first and last sentences stay intact; from the second sentence on, every second
word loses its second half (the larger half for odd lengths), up to 12 gaps per passage.
Scoring is exact: 1 for the right letters, 0.5 when only an accent/umlaut is off.
"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

from sqlalchemy import Connection, text

from app.config import AppConfig
from app.level.ctest_texts import LEVELS, TEXTS
from app.timeutil import to_iso, utc_now

WORD = re.compile(r"[^\W\d_]+")
SENTENCE = re.compile(r"(?<=[.!?:])\s+")
MAX_GAPS = 12
PASS, STRONG, PARTIAL = 0.6, 0.75, 0.4


class CTestError(ValueError):
    pass


def available(lang: str) -> bool:
    return lang in TEXTS


def make_gaps(passage: str, max_gaps: int = MAX_GAPS) -> list[dict[str, Any]]:
    """Segments: {'text': ...} or {'gap': n, 'shown': 'Ver', 'missing': 'käufer'} (answers removed before sending)."""
    sentences = SENTENCE.split(passage.strip())
    segments: list[dict[str, Any]] = []
    gaps = 0
    counter = 0
    for index, sentence in enumerate(sentences):
        prefix = "" if index == 0 else " "
        if index == 0 or index == len(sentences) - 1 or gaps >= max_gaps:
            segments.append({"text": prefix + sentence})
            continue
        cursor = 0
        buffer = prefix
        for match in WORD.finditer(sentence):
            word = match.group()
            if len(word) < 2:
                continue
            counter += 1
            if counter % 2 == 0 and gaps < max_gaps:
                keep = len(word) // 2
                buffer += sentence[cursor : match.start()]
                segments.append({"text": buffer})
                segments.append({"gap": gaps, "shown": word[:keep], "missing": word[keep:]})
                buffer = ""
                cursor = match.end()
                gaps += 1
        segments.append({"text": buffer + sentence[cursor:]})
    return [s for s in segments if "gap" in s or s["text"]]


def _fold(value: str) -> str:
    value = value.replace("ß", "ss")
    return "".join(c for c in unicodedata.normalize("NFD", value) if unicodedata.category(c) != "Mn").casefold()


def score_answer(expected: str, given: str) -> float:
    given = unicodedata.normalize("NFC", given.strip())
    if given.lower() == expected.lower():  # lower(), not casefold(): ß vs ss is a spelling error
        return 1.0
    if given and _fold(given) == _fold(expected):
        return 0.5
    return 0.0


def start(conn: Connection, lang: str) -> dict[str, Any]:
    if not available(lang):
        raise CTestError("The reading check is not available for this language yet.")
    assessment_id = conn.execute(
        text("INSERT INTO assessments (language_code, skill, method) VALUES (:l, 'reading', 'c_test')"), {"l": lang}
    ).lastrowid
    passages = []
    seq = 0
    for level in LEVELS:
        public: list[dict[str, Any]] = []
        for segment in make_gaps(TEXTS[lang][level]):
            if "gap" not in segment:
                public.append(segment)
                continue
            seq += 1
            item_id = conn.execute(
                text(
                    "INSERT INTO assessment_items (assessment_id, seq, item_type, difficulty, prompt_json) "
                    "VALUES (:a, :seq, 'c_gap', :d, :p)"
                ),
                {
                    "a": assessment_id,
                    "seq": seq,
                    "d": LEVELS.index(level),
                    "p": json.dumps({"level": level, **segment}, ensure_ascii=False),
                },
            ).lastrowid
            public.append({"gap": item_id, "shown": segment["shown"], "size": len(segment["missing"])})
        passages.append({"level": level, "segments": public})
    return {"assessment_id": assessment_id, "passages": passages}


def submit(conn: Connection, cfg: AppConfig, assessment_id: int, answers: dict[int, str]) -> dict[str, Any]:
    row = conn.execute(
        text("SELECT language_code, status, method FROM assessments WHERE id = :id"), {"id": assessment_id}
    ).first()
    if not row or row[2] != "c_test":
        raise CTestError("no such reading check")
    if row[1] != "in_progress":
        raise CTestError("this reading check was already submitted")
    lang = row[0]
    items = conn.execute(
        text("SELECT id, prompt_json FROM assessment_items WHERE assessment_id = :id ORDER BY seq"), {"id": assessment_id}
    ).all()

    per_level: dict[str, list[float]] = {level: [] for level in LEVELS}
    review: list[dict[str, Any]] = []
    for item_id, prompt_json in items:
        prompt = json.loads(prompt_json)
        given = str(answers.get(item_id, ""))[:40]
        score = score_answer(prompt["missing"], given)
        per_level[prompt["level"]].append(score)
        conn.execute(
            text("UPDATE assessment_items SET response = :r, score = :s WHERE id = :id"),
            {"r": given, "s": score, "id": item_id},
        )
        review.append({"id": item_id, "expected": prompt["shown"] + prompt["missing"], "given": prompt["shown"] + given, "score": score})

    scores = {level: round(sum(v) / len(v), 3) if v else 0.0 for level, v in per_level.items()}
    band, band_low, band_high = _band(scores)
    total = sum(sum(v) for v in per_level.values()) / max(1, sum(len(v) for v in per_level.values()))
    result = {"scores": scores, "band": band, "band_low": band_low, "band_high": band_high, "overall": round(total, 3)}
    now = to_iso(utc_now())
    theta = (LEVELS.index(band) + 1) if band in LEVELS else 0
    conn.execute(
        text(
            "UPDATE assessments SET status = 'done', theta = :t, theta_se = 0.5, raw_score = :raw, result_json = :r, "
            "finished_at = :now WHERE id = :id"
        ),
        {"t": theta, "raw": total, "r": json.dumps(result), "now": now, "id": assessment_id},
    )
    conn.execute(
        text(
            "INSERT INTO skill_estimates (language_code, skill, theta, theta_se, band, band_low, band_high, "
            "last_tested_at, updated_at) VALUES (:l, 'reading', :t, 0.5, :b, :bl, :bh, :now, :now) "
            "ON CONFLICT(language_code, skill) DO UPDATE SET theta = excluded.theta, theta_se = excluded.theta_se, "
            "band = excluded.band, band_low = excluded.band_low, band_high = excluded.band_high, "
            "last_tested_at = excluded.last_tested_at, updated_at = excluded.updated_at"
        ),
        {"l": lang, "t": theta, "b": band, "bl": band_low, "bh": band_high, "now": now},
    )
    return {"result": result, "review": review}


def _band(scores: dict[str, float]) -> tuple[str, str, str]:
    passed = [level for level in LEVELS if scores[level] >= PASS]
    band = passed[-1] if passed else "A1"
    index = LEVELS.index(band) if band in LEVELS else -1
    nxt = LEVELS[index + 1] if index + 1 < len(LEVELS) else None
    high = nxt if nxt and scores[nxt] >= PARTIAL else band
    if band == "A1" or scores[band] >= STRONG:
        low = band
    else:
        low = LEVELS[index - 1] if index > 0 else "A1"
    return band, low, high
