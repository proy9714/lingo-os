"""Adaptive vocabulary test (ARCHITECTURE §6.12).

Model: you know a word of frequency rank r with probability p = 1 / (1 + (r / r50)^k).
Each real item is answered "no", "yes + right meaning" or "yes + wrong/unsure meaning":

    P(no)          = (1 - p)(1 - fa) + p·slip
    P(yes, right)  = p(1 - slip)·c + (1 - p)·fa·g
    P(yes, wrong)  = p(1 - slip)(1 - c) + (1 - p)·fa·(1 - g)

fa (saying yes to words you don't know) is learned from pseudo-words; c is the chance
of picking the right meaning when you know the word; g = 1/4 is a blind guess.
The posterior over log(r50) lives on a grid; each next word sits at the current
estimate of your frontier, and the test stops once the 90% range is narrow enough.
"""

from __future__ import annotations

import json
import math
import random
from typing import Any

import numpy as np
from sqlalchemy import Connection, text

from app.config import AppConfig
from app.engine.profile import apply_measurement, band_for_size, get_profile
from app.engine.vocab_model import DEFAULT_K, expected_vocabulary
from app.level import items as item_source
from app.services import vocab
from app.timeutil import to_iso, utc_now

GRID = np.linspace(math.log(30), math.log(40_000), 240)
SLIP, KNOWN_CORRECT, GUESS = 0.05, 0.92, 0.25
PRIOR_SD = 1.2
FIXED_START = (300, 2500, 9000)
PSEUDO_AT = {4, 9, 14, 20, 26, 33, 40, 47}
MIN_REAL, MAX_REAL, TARGET_RATIO = 24, 45, 2.2


class TestError(ValueError):
    pass


# ------------------------------------------------------------------ state


def _load(conn: Connection, assessment_id: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    row = conn.execute(
        text("SELECT id, language_code, status, result_json, method FROM assessments WHERE id = :id"), {"id": assessment_id}
    ).first()
    if not row or row[4] != "vocab_adaptive":
        raise TestError("no such vocabulary test")
    assessment = {"id": row[0], "lang": row[1], "status": row[2], "meta": json.loads(row[3])}
    rows = conn.execute(
        text(
            "SELECT id, seq, item_type, prompt_json, response, score FROM assessment_items "
            "WHERE assessment_id = :id ORDER BY seq"
        ),
        {"id": assessment_id},
    ).all()
    items = [
        {
            "id": r[0],
            "seq": r[1],
            "pseudo": r[2] == "pseudo_word",
            "prompt": json.loads(r[3]),
            "response": json.loads(r[4]) if r[4] else None,
            "score": r[5],
        }
        for r in rows
    ]
    return assessment, items


def posterior(items: list[dict[str, Any]], prior_mu: float, k: float) -> tuple[np.ndarray, float]:
    pseudo = [i for i in items if i["pseudo"] and i["response"] and "category" in i["response"]]
    false_alarms = sum(1 for i in pseudo if i["response"]["category"] != "no")
    fa = (1 + false_alarms) / (10 + len(pseudo))
    log_w = -0.5 * ((GRID - prior_mu) / PRIOR_SD) ** 2
    r50 = np.exp(GRID)
    for item in items:
        if item["pseudo"] or not item["response"] or "category" not in item["response"]:
            continue
        p = 1.0 / (1.0 + (item["prompt"]["rank"] / r50) ** k)
        category = item["response"]["category"]
        if category == "no":
            likelihood = (1 - p) * (1 - fa) + p * SLIP
        elif category == "yes_right":
            likelihood = p * (1 - SLIP) * KNOWN_CORRECT + (1 - p) * fa * GUESS
        else:
            likelihood = p * (1 - SLIP) * (1 - KNOWN_CORRECT) + (1 - p) * fa * (1 - GUESS)
        log_w += np.log(likelihood + 1e-12)
    w = np.exp(log_w - log_w.max())
    return w / w.sum(), fa


def _quantile(w: np.ndarray, values: np.ndarray, q: float) -> float:
    return float(values[min(int(np.searchsorted(np.cumsum(w), q)), len(values) - 1)])


# ------------------------------------------------------------------ flow


def start(conn: Connection, dict_conn: Connection, lang: str) -> dict[str, Any]:
    profile = get_profile(conn, lang)
    prior_mu = math.log(profile["r50"]) if profile else math.log(800)
    k = profile["k"] if profile else DEFAULT_K
    has_dictionary = dict_conn.execute(
        text("SELECT 1 FROM dictionaries WHERE language_code = :l AND enabled = 1"), {"l": lang}
    ).first()
    if not has_dictionary:
        raise TestError("The vocabulary test needs a dictionary for this language. Run `lingo dict import` first.")
    meta = {"prior_mu": prior_mu, "k": k, "seed": random.randrange(1 << 30)}
    assessment_id = conn.execute(
        text(
            "INSERT INTO assessments (language_code, skill, method, result_json) "
            "VALUES (:l, 'vocabulary', 'vocab_adaptive', :meta)"
        ),
        {"l": lang, "meta": json.dumps(meta)},
    ).lastrowid
    return {"assessment_id": assessment_id, **_next(conn, dict_conn, assessment_id)}


def answer(conn: Connection, dict_conn: Connection, cfg: AppConfig, assessment_id: int, item_id: int, known: bool) -> dict[str, Any]:
    assessment, items = _load(conn, assessment_id)
    item = _open_item(assessment, items, item_id)
    if not known:
        _record(conn, item, {"known": False, "category": "no"}, 0.0)
        return _advance(conn, dict_conn, cfg, assessment_id)
    # "Yes" → check it with a meaning question.
    rng = random.Random(assessment["meta"]["seed"] + item["seq"])
    used = {i["prompt"]["word"].lower() for i in items}
    prompt = dict(item["prompt"])
    if item["pseudo"]:
        options = item_source.distractors(dict_conn, assessment["lang"], 2000, "", used, rng, n=4)
        correct = -1
    else:
        wrong = item_source.distractors(dict_conn, assessment["lang"], prompt["rank"], prompt["gloss"], used, rng)
        options = [prompt["gloss"], *wrong]
        rng.shuffle(options)
        correct = options.index(prompt["gloss"])
    prompt.update({"options": options, "correct": correct})
    conn.execute(
        text("UPDATE assessment_items SET prompt_json = :p, response = :r WHERE id = :id"),
        {"p": json.dumps(prompt, ensure_ascii=False), "r": json.dumps({"known": True}), "id": item["id"]},
    )
    return {"done": False, "item": _payload(item["id"], item["seq"], prompt, "meaning", items)}


def meaning(conn: Connection, dict_conn: Connection, cfg: AppConfig, assessment_id: int, item_id: int, choice: int | None) -> dict[str, Any]:
    assessment, items = _load(conn, assessment_id)
    item = _open_item(assessment, items, item_id, expect_meaning=True)
    right = choice is not None and choice == item["prompt"]["correct"]
    _record(conn, item, {"known": True, "choice": choice, "category": "yes_right" if right else "yes_wrong"}, 1.0 if right else 0.5)
    return _advance(conn, dict_conn, cfg, assessment_id)


def finish(conn: Connection, cfg: AppConfig, assessment_id: int) -> dict[str, Any]:
    assessment, items = _load(conn, assessment_id)
    if assessment["status"] != "in_progress":
        raise TestError("this test is already finished")
    answered = [i for i in items if not i["pseudo"] and i["response"] and "category" in i["response"]]
    if len(answered) < 10:
        conn.execute(
            text("UPDATE assessments SET status = 'abandoned', finished_at = :t WHERE id = :id"),
            {"t": to_iso(utc_now()), "id": assessment_id},
        )
        return {"done": True, "abandoned": True, "reason": "Fewer than 10 words answered, so nothing was saved."}
    return _finalize(conn, cfg, assessment, items)


def _open_item(assessment: dict[str, Any], items: list[dict[str, Any]], item_id: int, expect_meaning: bool = False) -> dict[str, Any]:
    if assessment["status"] != "in_progress":
        raise TestError("this test is already finished")
    item = next((i for i in items if i["id"] == item_id), None)
    if not item:
        raise TestError("no such item in this test")
    response = item["response"] or {}
    if "category" in response:
        raise TestError("this word was already answered")
    if expect_meaning and not response.get("known"):
        raise TestError("answer whether you know the word first")
    return item


def _record(conn: Connection, item: dict[str, Any], response: dict[str, Any], score: float) -> None:
    conn.execute(
        text("UPDATE assessment_items SET response = :r, score = :s WHERE id = :id"),
        {"r": json.dumps(response), "s": score, "id": item["id"]},
    )


def _advance(conn: Connection, dict_conn: Connection, cfg: AppConfig, assessment_id: int) -> dict[str, Any]:
    assessment, items = _load(conn, assessment_id)
    w, _fa = posterior(items, assessment["meta"]["prior_mu"], assessment["meta"]["k"])
    mu = float(np.sum(w * GRID))
    last = items[-1]
    conn.execute(text("UPDATE assessment_items SET theta_after = :t WHERE id = :id"), {"t": mu, "id": last["id"]})
    real = [i for i in items if not i["pseudo"] and i["response"] and "category" in i["response"]]
    ratio = math.exp(_quantile(w, GRID, 0.95) - _quantile(w, GRID, 0.05))
    if len(real) >= MAX_REAL or (len(real) >= MIN_REAL and ratio <= TARGET_RATIO):
        return _finalize(conn, cfg, assessment, items)
    return _next(conn, dict_conn, assessment_id)


def _next(conn: Connection, dict_conn: Connection, assessment_id: int) -> dict[str, Any]:
    assessment, items = _load(conn, assessment_id)
    lang, meta = assessment["lang"], assessment["meta"]
    seq = len(items) + 1
    rng = random.Random(meta["seed"] + seq * 7919)
    used = {i["prompt"]["word"].lower() for i in items}

    prompt: dict[str, Any] | None = None
    item_type = "yes_no"
    if seq in PSEUDO_AT:
        fake = item_source.pseudo_word(dict_conn, lang, rng)
        if fake:
            prompt, item_type = {"word": fake, "rank": None, "pseudo": True}, "pseudo_word"
    if prompt is None:
        real_count = sum(1 for i in items if not i["pseudo"])
        if real_count < len(FIXED_START):
            target = FIXED_START[real_count]
        else:
            w, _ = posterior(items, meta["prior_mu"], meta["k"])
            target = math.exp(float(np.sum(w * GRID)) + rng.gauss(0, 0.4))
        candidate = item_source.candidate_near(dict_conn, lang, int(min(max(target, 20), 30_000)), used)
        if candidate is None:
            raise TestError("could not find a suitable test word; is the dictionary imported?")
        prompt = {"word": candidate.word, "reading": candidate.reading, "rank": candidate.rank, "gloss": candidate.gloss}

    item_id = conn.execute(
        text(
            "INSERT INTO assessment_items (assessment_id, seq, item_type, difficulty, prompt_json) "
            "VALUES (:a, :seq, :type, :diff, :p)"
        ),
        {
            "a": assessment_id,
            "seq": seq,
            "type": item_type,
            "diff": math.log(prompt["rank"]) if prompt.get("rank") else None,
            "p": json.dumps(prompt, ensure_ascii=False),
        },
    ).lastrowid
    return {"done": False, "item": _payload(item_id, seq, prompt, "yesno", items)}


def _payload(item_id: int, seq: int, prompt: dict[str, Any], step: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    answered = sum(1 for i in items if not i["pseudo"] and i["response"] and "category" in i["response"])
    payload = {"id": item_id, "seq": seq, "word": prompt["word"], "step": step, "answered": answered, "typical_length": 35}
    if step == "meaning":
        payload["options"] = prompt["options"]
    return payload


def _finalize(conn: Connection, cfg: AppConfig, assessment: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    lang, meta = assessment["lang"], assessment["meta"]
    k = meta["k"]
    w, fa = posterior(items, meta["prior_mu"], k)
    sizes = np.array([expected_vocabulary(round(math.exp(g), 3), k) for g in GRID])
    mu = float(np.sum(w * GRID))
    sd = float(math.sqrt(np.sum(w * (GRID - mu) ** 2)))
    size = float(np.sum(w * sizes))
    low, high = _quantile(w, sizes, 0.05), _quantile(w, sizes, 0.95)
    r50 = math.exp(mu)

    profile = apply_measurement(conn, cfg, lang, r50=r50, k=k, size=size)
    band, jlpt = band_for_size(cfg.baselines, lang, size)
    band_low, jlpt_low = band_for_size(cfg.baselines, lang, low)
    band_high, jlpt_high = band_for_size(cfg.baselines, lang, high)

    real = [i for i in items if not i["pseudo"] and i["response"] and "category" in i["response"]]
    pseudo = [i for i in items if i["pseudo"] and i["response"] and "category" in i["response"]]
    result = {
        "vocabulary": int(round(size, -1)),
        "low": int(round(low, -1)),
        "high": int(round(high, -1)),
        "band": band,
        "band_low": band_low,
        "band_high": band_high,
        "jlpt": jlpt,
        "jlpt_low": jlpt_low,
        "jlpt_high": jlpt_high,
        "r50": round(r50, 1),
        "k": k,
        "words_answered": len(real),
        "pseudo_shown": len(pseudo),
        "pseudo_claimed": sum(1 for i in pseudo if i["response"]["category"] != "no"),
        "false_alarm_rate": round(fa, 3),
        "profile_version": profile.get("version"),
    }
    now = to_iso(utc_now())
    conn.execute(
        text(
            "UPDATE assessments SET status = 'done', theta = :t, theta_se = :se, raw_score = :raw, result_json = :r, "
            "finished_at = :now WHERE id = :id"
        ),
        {
            "t": mu,
            "se": sd,
            "raw": sum(1 for i in real if i["response"]["category"] == "yes_right") / max(1, len(real)),
            "r": json.dumps({**meta, **result}),
            "now": now,
            "id": assessment["id"],
        },
    )
    conn.execute(
        text(
            "INSERT INTO skill_estimates (language_code, skill, theta, theta_se, band, band_low, band_high, "
            "last_tested_at, updated_at) VALUES (:l, 'vocabulary', :t, :se, :b, :bl, :bh, :now, :now) "
            "ON CONFLICT(language_code, skill) DO UPDATE SET theta = excluded.theta, theta_se = excluded.theta_se, "
            "band = excluded.band, band_low = excluded.band_low, band_high = excluded.band_high, "
            "last_tested_at = excluded.last_tested_at, updated_at = excluded.updated_at"
        ),
        {"l": lang, "t": mu, "se": sd, "b": band, "bl": band_low, "bh": band_high, "now": now},
    )
    # Words you proved you know (right meaning) become 'known'; others are logged as evidence only.
    for item in real:
        prompt, category = item["prompt"], item["response"]["category"]
        if category == "yes_right":
            vocab.set_status(conn, lang, prompt["word"], prompt.get("reading", ""), "known", rank=prompt["rank"], event="test_known")
        else:
            lexeme_id = vocab.ensure_lexeme(conn, lang, prompt["word"], prompt.get("reading", ""), rank=prompt["rank"])
            conn.execute(
                text(
                    "INSERT OR IGNORE INTO user_words (lexeme_id, status, p_known, first_seen_at, last_seen_at) "
                    "VALUES (:id, 'seen', 0.1, :now, :now)"
                ),
                {"id": lexeme_id, "now": now},
            )
            conn.execute(
                text("INSERT INTO word_events (lexeme_id, event, value) VALUES (:id, 'test_unknown', :c)"),
                {"id": lexeme_id, "c": category},
            )
    return {"done": True, "result": result}
