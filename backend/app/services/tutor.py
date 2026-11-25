"""AI conversation tutor (ARCHITECTURE §6.8): profile-aware prompt, vocabulary governor, after-session review.

The chat model only ever writes plain text. Corrections, grammar points and a summary are extracted afterwards by
a separate structured call (`tutor_postprocess` job), which updates grammar tracking.

Model calls take seconds, so the public functions take the Engine and never call a model inside a write transaction
(SQLite has one writer; the gateway logs each call on its own connection).
"""

from __future__ import annotations

import json
import re
from string import Template
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import Connection, Engine, text

from app.ai.gateway import Gateway, load_prompt
from app.engine.profile import get_profile
from app.services.annotate import annotate
from app.services.explain import LANGUAGE_NAMES

MIN_COVERAGE = 0.92  # replies below this share of probably-known words are simplified once
KICKOFF = "(The learner has opened the chat. Start now.)"

REGISTER = {
    "de": "Address the learner with du.",
    "es": "Address the learner with tú.",
    "ja": "Use the polite です/ます style.",
    "zh": "Use simple, natural Mandarin in simplified characters; address the learner with 你.",
    "fr": "Address the learner with tu.",
    "pt": "Address the learner with você (Brazilian usage) unless they write in European Portuguese, then use tu.",
    "ru": "Address the learner with ты.",
    "ko": "Use the polite 해요 style (존댓말).",
    "it": "Address the learner with tu.",
    "hi": "Address the learner with आप; write in Devanagari, with everyday words rather than Sanskritised ones.",
    "bn": "Address the learner with আপনি; write in Bengali script, in standard colloquial Bengali (চলিত ভাষা).",
    "ar": "Use Modern Standard Arabic (فصحى) without vowel marks except where a word would be ambiguous; if the learner "
          "chose Egyptian Arabic, speak Egyptian colloquial instead. Address the learner with أنت.",
}
MAX_WORDS = {"A1": 6, "A2": 8, "B1": 12, "B2": 16, "C1": 20, "C2": 22, "N5": 6, "N4": 8, "N3": 12, "N2": 16, "N1": 20}

MODES = {"conversation", "roleplay", "content_discussion", "correction_drill"}

SCENARIOS: dict[str, list[dict[str, str]]] = {
    "de": [
        {"id": "buergeramt", "title": "Registering your address at the Bürgeramt",
         "setting": "a Bürgeramt in Berlin; the learner needs to register their new flat (Anmeldung)",
         "you": "a busy but friendly clerk", "learner": "a newcomer who just moved"},
        {"id": "baeckerei", "title": "Ordering at a bakery",
         "setting": "a small bakery on a Saturday morning", "you": "the baker", "learner": "a customer"},
        {"id": "wg", "title": "Interview for a room in a shared flat",
         "setting": "a WG-Casting in Munich", "you": "one of the flatmates", "learner": "someone who wants the room"},
        {"id": "arzt", "title": "At the doctor's",
         "setting": "a family doctor's practice", "you": "the doctor", "learner": "a patient with a cold"},
    ],
    "es": [
        {"id": "cafe", "title": "Ordering at a café in Madrid",
         "setting": "a busy café in Madrid", "you": "the waiter", "learner": "a customer"},
        {"id": "direcciones", "title": "Asking for directions in Mexico City",
         "setting": "a street in Mexico City", "you": "a helpful local", "learner": "a visitor who is a bit lost"},
        {"id": "piso", "title": "Viewing a flat to rent",
         "setting": "a flat for rent in Valencia", "you": "the landlord", "learner": "someone looking for a flat"},
        {"id": "farmacia", "title": "At the pharmacy",
         "setting": "a pharmacy in Buenos Aires", "you": "the pharmacist", "learner": "a customer with a headache"},
    ],
    "ja": [
        {"id": "konbini", "title": "At a convenience store",
         "setting": "a convenience store in Tokyo", "you": "the clerk", "learner": "a customer"},
        {"id": "restaurant", "title": "Ordering at a restaurant",
         "setting": "a small ramen restaurant", "you": "the staff member", "learner": "a customer"},
        {"id": "eki", "title": "Asking the way at a station",
         "setting": "a big train station in Osaka", "you": "a station worker", "learner": "a traveller"},
        {"id": "baito", "title": "A part-time job interview",
         "setting": "an interview for a part-time job at a café", "you": "the manager", "learner": "the applicant"},
    ],
    "zh": [
        {"id": "canting", "title": "Ordering at a restaurant in Beijing",
         "setting": "a busy family restaurant in Beijing", "you": "the waiter", "learner": "a customer"},
        {"id": "ditie", "title": "Buying a metro card in Shanghai",
         "setting": "a metro station in Shanghai", "you": "a helpful station worker", "learner": "a visitor"},
        {"id": "zufang", "title": "Renting a flat",
         "setting": "an estate agent's office in Chengdu", "you": "the agent", "learner": "someone looking for a flat"},
        {"id": "yiyuan", "title": "At the doctor's",
         "setting": "a clinic", "you": "the doctor", "learner": "a patient with a sore throat"},
    ],
    "fr": [
        {"id": "boulangerie", "title": "At the bakery",
         "setting": "a bakery in Lyon on a Sunday morning", "you": "the baker", "learner": "a customer"},
        {"id": "prefecture", "title": "Asking about a residence permit",
         "setting": "a préfecture office in Paris", "you": "a busy but polite clerk", "learner": "a newcomer"},
        {"id": "colocation", "title": "Visiting a flat-share",
         "setting": "a colocation in Bordeaux", "you": "one of the flatmates", "learner": "someone who wants the room"},
        {"id": "pharmacie", "title": "At the pharmacy",
         "setting": "a pharmacy in Montréal", "you": "the pharmacist", "learner": "a customer with a cough"},
    ],
    "pt": [
        {"id": "padaria", "title": "At a padaria",
         "setting": "a padaria in São Paulo in the morning", "you": "the person at the counter", "learner": "a customer"},
        {"id": "uber", "title": "Chatting with a driver",
         "setting": "a ride across Rio de Janeiro", "you": "a chatty driver", "learner": "a passenger"},
        {"id": "apartamento", "title": "Viewing a flat to rent",
         "setting": "a flat for rent in Lisbon", "you": "the landlady", "learner": "someone looking for a flat"},
        {"id": "medico", "title": "At the doctor's",
         "setting": "a health centre", "you": "the doctor", "learner": "a patient with a headache"},
    ],
    "ru": [
        {"id": "kafe", "title": "Ordering at a café in Moscow",
         "setting": "a small café in Moscow", "you": "the waiter", "learner": "a customer"},
        {"id": "vokzal", "title": "Buying a train ticket",
         "setting": "a railway station ticket office in St Petersburg", "you": "the cashier", "learner": "a traveller"},
        {"id": "kvartira", "title": "Renting a room",
         "setting": "a flat in Kazan", "you": "the landlady", "learner": "a student who needs a room"},
        {"id": "apteka", "title": "At the pharmacy",
         "setting": "a pharmacy", "you": "the pharmacist", "learner": "a customer with a cold"},
    ],
    "ko": [
        {"id": "pyeonuijeom", "title": "At a convenience store",
         "setting": "a convenience store in Seoul", "you": "the clerk", "learner": "a customer"},
        {"id": "sikdang", "title": "Ordering at a restaurant",
         "setting": "a Korean barbecue restaurant", "you": "the staff member", "learner": "a customer"},
        {"id": "jihacheol", "title": "Asking the way in the subway",
         "setting": "a subway station in Busan", "you": "a friendly local", "learner": "a visitor"},
        {"id": "alba", "title": "A part-time job interview",
         "setting": "an interview at a café", "you": "the manager", "learner": "the applicant"},
    ],
    "it": [
        {"id": "bar", "title": "Ordering at a bar",
         "setting": "a bar in Rome in the morning", "you": "the barista", "learner": "a customer"},
        {"id": "treno", "title": "Buying a train ticket",
         "setting": "the ticket office at Milano Centrale", "you": "the clerk", "learner": "a traveller"},
        {"id": "affitto", "title": "Viewing a flat to rent",
         "setting": "a flat in Bologna", "you": "the landlord", "learner": "a student"},
        {"id": "farmacia", "title": "At the pharmacy",
         "setting": "a pharmacy in Naples", "you": "the pharmacist", "learner": "a customer with a sore throat"},
    ],
    "hi": [
        {"id": "sabzi", "title": "Buying vegetables at the market",
         "setting": "a vegetable stall in a Delhi market", "you": "the vegetable seller", "learner": "a customer"},
        {"id": "auto", "title": "Taking an auto-rickshaw",
         "setting": "outside a metro station in Jaipur", "you": "the auto driver", "learner": "a passenger"},
        {"id": "train", "title": "Asking about a train",
         "setting": "the enquiry counter at Lucknow station", "you": "the railway clerk", "learner": "a traveller"},
        {"id": "doctor", "title": "At the doctor's",
         "setting": "a clinic in Mumbai", "you": "the doctor", "learner": "a patient with a fever"},
    ],
    "bn": [
        {"id": "bazar", "title": "Shopping for fish at the bazaar",
         "setting": "a fish market in Dhaka", "you": "the fishmonger", "learner": "a customer"},
        {"id": "rickshaw", "title": "Hiring a rickshaw",
         "setting": "a street in Kolkata", "you": "the rickshaw puller", "learner": "a passenger"},
        {"id": "cha", "title": "At a tea stall",
         "setting": "a roadside tea stall", "you": "the tea seller", "learner": "a regular customer"},
        {"id": "bari", "title": "Renting a room",
         "setting": "a flat in Chattogram", "you": "the landlord", "learner": "a student looking for a room"},
    ],
    "ar": [
        {"id": "souk", "title": "Bargaining in the souk",
         "setting": "a spice shop in an old market", "you": "the shopkeeper", "learner": "a customer"},
        {"id": "taxi", "title": "Taking a taxi",
         "setting": "a taxi in Cairo", "you": "the taxi driver", "learner": "a passenger going to the museum"},
        {"id": "restaurant", "title": "Ordering at a restaurant",
         "setting": "a family restaurant in Amman", "you": "the waiter", "learner": "a customer"},
        {"id": "pharmacy", "title": "At the pharmacy",
         "setting": "a pharmacy in Rabat", "you": "the pharmacist", "learner": "a customer with a headache"},
    ],
}


class TutorError(Exception):
    pass


# ------------------------------------------------------------------ prompt


def _language(conn: Connection, lang: str) -> str:
    return conn.execute(text("SELECT name FROM languages WHERE code = :c"), {"c": lang}).scalar() or LANGUAGE_NAMES.get(lang, lang)


def active_instructions(conn: Connection, lang: str) -> dict[str, Any]:
    """This week's coaching brief; a default one is created the first time."""
    row = conn.execute(
        text("SELECT id, instructions_md, style_json FROM tutor_instructions WHERE language_code = :l AND is_active = 1"),
        {"l": lang},
    ).first()
    if not row:
        style = {"speech_rate": 0.9, "correction": "recast"}
        new_id = conn.execute(
            text(
                "INSERT INTO tutor_instructions (language_code, version, origin, instructions_md, style_json, is_active) "
                "VALUES (:l, COALESCE((SELECT MAX(version) FROM tutor_instructions WHERE language_code = :l), 0) + 1, "
                "'default', :md, :style, 1)"
            ),
            {"l": lang, "md": "No special notes yet.", "style": json.dumps(style)},
        ).lastrowid
        return {"id": new_id, "instructions_md": "No special notes yet.", "style": style}
    return {"id": row[0], "instructions_md": row[1], "style": json.loads(row[2] or "{}")}


def _focus_words(conn: Connection, lang: str, limit: int = 15) -> list[str]:
    rows = conn.execute(
        text(
            "SELECT l.lemma FROM user_words w JOIN lexemes l ON l.id = w.lexeme_id WHERE l.language_code = :l "
            "AND w.status = 'learning' ORDER BY COALESCE(w.status_changed_at, w.last_seen_at) DESC LIMIT :n"
        ),
        {"l": lang, "n": limit},
    ).all()
    return [r[0] for r in rows]


def _weak_grammar(conn: Connection, lang: str, limit: int = 3) -> list[str]:
    rows = conn.execute(
        text(
            "SELECT g.title FROM user_grammar u JOIN grammar_points g ON g.id = u.grammar_point_id WHERE g.language_code = :l "
            "AND u.status IN ('weak', 'practicing') ORDER BY u.mastery, u.errors DESC LIMIT :n"
        ),
        {"l": lang, "n": limit},
    ).all()
    return [r[0] for r in rows]


def _mode_block(conn: Connection, lang: str, mode: str, scenario: str | None, content_item_id: int | None, weak: list[str]) -> str:
    if mode == "roleplay":
        card = next((s for s in SCENARIOS.get(lang, []) if s["id"] == scenario), None)
        if not card:
            raise TutorError("unknown role-play scenario")
        return (
            f"Role-play: {card['setting']}. You are {card['you']}; the learner is {card['learner']}. "
            "Stay in your role, keep the scene realistic, and open it with your first line."
        )
    if mode == "content_discussion":
        row = conn.execute(text("SELECT title, type FROM content_items WHERE id = :i"), {"i": content_item_id}).first()
        if not row:
            raise TutorError("pick something from your library to talk about")
        words = conn.execute(
            text(
                "SELECT l.lemma FROM content_lemmas cl JOIN lexemes l ON l.id = cl.lexeme_id WHERE cl.content_item_id = :i "
                "AND l.freq_rank BETWEEN 800 AND 8000 ORDER BY cl.count DESC LIMIT 12"
            ),
            {"i": content_item_id},
        ).all()
        verb = "watched" if row[1] in {"youtube", "video", "audio", "podcast_episode"} else "read"
        return (
            f"Talk with the learner about \"{row[0]}\", which they recently {verb}. Useful words from it: "
            f"{', '.join(w[0] for w in words) or 'none listed'}. Ask what they thought, one question at a time, and share "
            "your own short opinions too."
        )
    if mode == "correction_drill":
        target = ", ".join(weak) if weak else "everyday sentence patterns at this level"
        return (
            f"Practice session for: {target}. Create small, natural situations where the learner needs this grammar. "
            "Recast mistakes, and after two or three exchanges on one point, move to a new situation."
        )
    return "Free conversation. Greet the learner and ask one easy question about their day or their interests."


def build_system_prompt(
    conn: Connection, lang: str, mode: str, scenario: str | None = None, content_item_id: int | None = None
) -> tuple[str, dict[str, Any]]:
    profile = get_profile(conn, lang) or {}
    level = profile.get("level_alt") if lang == "ja" and profile.get("level_alt") else profile.get("level") or "A2"
    instructions = active_instructions(conn, lang)
    weak = _weak_grammar(conn, lang)
    focus = _focus_words(conn, lang)
    style = instructions["style"]
    max_words = int(style.get("max_sentence_words") or MAX_WORDS.get(str(level), 12))
    variables = {
        "language": _language(conn, lang),
        "level": level,
        "vocab_size": f"{round((profile.get('vocab_size') or 1000) / 100) * 100:,}",
        "max_words": max_words,
        "register": style.get("register_note") or REGISTER.get(lang, "Use a friendly, informal register."),
        "focus_words": ", ".join(focus) if focus else "none yet",
        "weak_grammar": ", ".join(weak) if weak else "none recorded yet",
        "brief": instructions["instructions_md"].strip() or "none",
        "mode": _mode_block(conn, lang, mode, scenario, content_item_id, weak),
    }
    prompt = load_prompt("tutor_system")
    return Template(prompt.system).substitute(variables), {
        "level": level, "max_words": max_words, "instructions_id": instructions["id"], "style": style,
        "language": variables["language"],
    }


# ------------------------------------------------------------------ conversation


def _history(conn: Connection, session_id: int) -> list[tuple[str, str]]:
    rows = conn.execute(
        text("SELECT role, text FROM tutor_messages WHERE session_id = :s AND role != 'system' ORDER BY seq"), {"s": session_id}
    ).all()
    return [("user", KICKOFF)] + [(r[0], r[1]) for r in rows]


def _add_message(conn: Connection, session_id: int, role: str, body: str, **extra: Any) -> int:
    seq = conn.execute(text("SELECT COALESCE(MAX(seq), 0) + 1 FROM tutor_messages WHERE session_id = :s"), {"s": session_id}).scalar()
    return conn.execute(
        text(
            "INSERT INTO tutor_messages (session_id, seq, role, input_mode, text, coverage, latency_ms, tokens_in, tokens_out) "
            "VALUES (:s, :seq, :role, :mode, :t, :cov, :ms, :tin, :tout)"
        ),
        {
            "s": session_id, "seq": seq, "role": role, "mode": extra.get("input_mode"), "t": body, "cov": extra.get("coverage"),
            "ms": extra.get("latency_ms"), "tin": extra.get("tokens_in"), "tout": extra.get("tokens_out"),
        },
    ).lastrowid


def _clean(reply: str) -> str:
    """Plain speakable text: strip markdown the model may add anyway."""
    reply = re.sub(r"[*_`#]+", "", reply)
    return re.sub(r"\n{2,}", "\n", reply).strip()


def _coverage(engine: Engine, lang: str, body: str) -> float | None:
    if not body:
        return None
    with engine.connect() as conn:
        return annotate(conn, lang, body)["summary"]["known_share"]


def _governed_reply(
    gateway: Gateway, engine: Engine, lang: str, system: str, history: list[tuple[str, str]], message: str, meta: dict[str, Any]
) -> tuple[str, float | None, dict[str, Any]]:
    """Ask the tutor, then simplify once if too many words are probably unknown (the vocabulary governor)."""
    reply, call = gateway.chat("tutor.chat", system, history, message)
    reply = _clean(reply)
    coverage = _coverage(engine, lang, reply)
    if coverage is not None and coverage < MIN_COVERAGE:
        prompt = load_prompt("tutor_rewrite")
        variables = {"language": meta["language"], "level": meta["level"], "max_words": meta["max_words"], "message": reply}
        simpler, _ = gateway.chat(
            "tutor.chat", Template(prompt.system).substitute(variables), [], Template(prompt.user).substitute(variables)
        )
        simpler = _clean(simpler)
        new_coverage = _coverage(engine, lang, simpler)
        if simpler and new_coverage is not None and new_coverage > coverage:
            reply, coverage = simpler, new_coverage
            call["simplified"] = True
    return reply, coverage, call


def message_view(conn: Connection, lang: str, row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["corrections"] = json.loads(out.pop("corrections_json") or "null")
    if out["role"] == "assistant":
        annotation = annotate(conn, lang, out["text"])
        out["tokens"] = annotation["tokens"]
    return out


def _messages(conn: Connection, session_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            "SELECT id, seq, role, input_mode, text, coverage, corrections_json, created_at FROM tutor_messages "
            "WHERE session_id = :s ORDER BY seq"
        ),
        {"s": session_id},
    ).mappings().all()
    return [dict(r) for r in rows]


def get_session(conn: Connection, session_id: int) -> dict[str, Any]:
    row = conn.execute(
        text(
            "SELECT id, language_code, mode, scenario, content_item_id, llm_model, summary_md, postprocessed, started_at, ended_at "
            "FROM tutor_sessions WHERE id = :s"
        ),
        {"s": session_id},
    ).mappings().first()
    if not row:
        raise TutorError("no such session")
    session = dict(row)
    lang = session["language_code"]
    session["messages"] = [message_view(conn, lang, m) for m in _messages(conn, session_id)]
    return session


def start_session(
    gateway: Gateway, engine: Engine, lang: str, mode: str, scenario: str | None = None, content_item_id: int | None = None
) -> dict[str, Any]:
    if mode not in MODES:
        raise TutorError(f"unknown mode '{mode}'")
    with engine.begin() as conn:
        system, meta = build_system_prompt(conn, lang, mode, scenario, content_item_id)
    opening, coverage, call = _governed_reply(gateway, engine, lang, system, [], KICKOFF, meta)
    with engine.begin() as conn:
        session_id = conn.execute(
            text(
                "INSERT INTO tutor_sessions (language_code, mode, scenario, content_item_id, instructions_id, system_prompt, "
                "llm_model, tts_voice) VALUES (:l, :m, :sc, :ci, :ii, :sp, :model, 'browser')"
            ),
            {
                "l": lang, "m": mode, "sc": scenario, "ci": content_item_id, "ii": meta["instructions_id"], "sp": system,
                "model": f"{call['provider']}/{call['model']}",
            },
        ).lastrowid
        _add_message(conn, session_id, "assistant", opening, coverage=coverage, **call)
        session = get_session(conn, session_id)
    session["speech_rate"] = float(meta["style"].get("speech_rate", 0.9))
    return session


def reply(gateway: Gateway, engine: Engine, session_id: int, user_text: str, input_mode: str = "text") -> dict[str, Any]:
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT language_code, system_prompt, ended_at FROM tutor_sessions WHERE id = :s"), {"s": session_id}
        ).first()
        if not row:
            raise TutorError("no such session")
        lang, system, ended = row
        if ended:
            raise TutorError("this conversation has ended; start a new one")
        profile = get_profile(conn, lang) or {}
        level = profile.get("level_alt") if lang == "ja" and profile.get("level_alt") else profile.get("level") or "A2"
        meta = {"level": level, "max_words": MAX_WORDS.get(str(level), 12), "language": _language(conn, lang)}
        history = _history(conn, session_id)
    answer, coverage, call = _governed_reply(gateway, engine, lang, system, history, user_text.strip(), meta)
    with engine.begin() as conn:
        user_id = _add_message(conn, session_id, "user", user_text.strip(), input_mode=input_mode)
        assistant_id = _add_message(conn, session_id, "assistant", answer, coverage=coverage, **call)
        messages = {m["id"]: m for m in _messages(conn, session_id)}
        return {
            "user": message_view(conn, lang, messages[user_id]),
            "assistant": message_view(conn, lang, messages[assistant_id]),
            "simplified": bool(call.get("simplified")),
        }


def end_session(conn: Connection, session_id: int) -> dict[str, Any]:
    from app.jobs.runner import enqueue

    users = conn.execute(
        text("SELECT COUNT(*) FROM tutor_messages WHERE session_id = :s AND role = 'user'"), {"s": session_id}
    ).scalar()
    conn.execute(
        text("UPDATE tutor_sessions SET ended_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = :s AND ended_at IS NULL"),
        {"s": session_id},
    )
    job_id = enqueue(conn, "tutor_postprocess", {"session_id": session_id}, dedupe=False) if users else None
    return {"ended": True, "review_job": job_id}


def list_sessions(conn: Connection, lang: str, limit: int = 20) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            "SELECT s.id, s.mode, s.scenario, s.started_at, s.ended_at, s.postprocessed, s.summary_md, "
            "(SELECT COUNT(*) FROM tutor_messages m WHERE m.session_id = s.id AND m.role = 'user') AS turns, "
            "ci.title FROM tutor_sessions s LEFT JOIN content_items ci ON ci.id = s.content_item_id "
            "WHERE s.language_code = :l ORDER BY s.started_at DESC LIMIT :n"
        ),
        {"l": lang, "n": limit},
    ).mappings().all()
    return [dict(r) for r in rows]


# ------------------------------------------------------------------ after the session


class Correction(BaseModel):
    turn: int = 0
    original: str
    corrected: str
    explanation: str = ""
    grammar: str = ""


class TutorReview(BaseModel):
    summary: str
    strengths: list[str] = Field(default_factory=list)
    corrections: list[Correction] = Field(default_factory=list)
    words_used: list[str] = Field(default_factory=list)


def _slug(name: str) -> str:
    return re.sub(r"[^\w]+", "_", name.lower()).strip("_")[:60]


def _record_grammar_error(conn: Connection, lang: str, name: str, message_id: int | None, fix: Correction) -> None:
    key = f"{lang}.{_slug(name)}"
    point_id = conn.execute(text("SELECT id FROM grammar_points WHERE key = :k"), {"k": key}).scalar()
    if not point_id:
        point_id = conn.execute(
            text("INSERT INTO grammar_points (language_code, key, title, origin) VALUES (:l, :k, :t, 'llm')"),
            {"l": lang, "k": key, "t": name[:120]},
        ).lastrowid
    conn.execute(
        text(
            "INSERT INTO user_grammar (grammar_point_id, status, mastery, errors, last_error_at) VALUES (:p, 'practicing', 0.4, 1, "
            "strftime('%Y-%m-%dT%H:%M:%fZ','now')) ON CONFLICT(grammar_point_id) DO UPDATE SET errors = errors + 1, "
            "mastery = MAX(0.05, mastery * 0.8), status = CASE WHEN errors + 1 >= 2 THEN 'weak' ELSE 'practicing' END, "
            "last_error_at = excluded.last_error_at, updated_at = excluded.last_error_at"
        ),
        {"p": point_id},
    )
    conn.execute(
        text(
            "INSERT INTO grammar_evidence (grammar_point_id, outcome, source, tutor_message_id, original_text, corrected_text, note) "
            "VALUES (:p, 'error', 'tutor', :m, :o, :c, :n)"
        ),
        {"p": point_id, "m": message_id, "o": fix.original, "c": fix.corrected, "n": fix.explanation},
    )


def postprocess(gateway: Gateway, engine: Engine, session_id: int) -> dict[str, Any]:
    with engine.connect() as conn:
        session = conn.execute(
            text("SELECT language_code, postprocessed FROM tutor_sessions WHERE id = :s"), {"s": session_id}
        ).first()
        if not session:
            raise TutorError("no such session")
        lang, done = session
        if done:
            return {"session_id": session_id, "skipped": "already reviewed"}
        messages = _messages(conn, session_id)
        profile = get_profile(conn, lang) or {}
        language = _language(conn, lang)
    user_ids: list[int] = []
    lines = []
    for m in messages:
        if m["role"] == "user":
            user_ids.append(m["id"])
            lines.append(f"L{len(user_ids)}: {m['text']}")
        elif m["role"] == "assistant":
            lines.append(f"T: {m['text']}")
    if not user_ids:
        return {"session_id": session_id, "skipped": "the learner said nothing"}
    variables = {"language": language, "level": profile.get("level") or "A2", "transcript": "\n".join(lines)}
    review, _ = gateway.structured("tutor.postprocess", "tutor_review", variables, TutorReview, cache=False)

    with engine.begin() as conn:
        by_message: dict[int, list[dict[str, Any]]] = {}
        for fix in review.corrections:
            if fix.original.strip() == fix.corrected.strip():
                continue
            message_id = user_ids[fix.turn - 1] if 1 <= fix.turn <= len(user_ids) else None
            if message_id:
                by_message.setdefault(message_id, []).append(fix.model_dump())
            if fix.grammar.strip():
                _record_grammar_error(conn, lang, fix.grammar.strip(), message_id, fix)
        for message_id, fixes in by_message.items():
            conn.execute(
                text("UPDATE tutor_messages SET corrections_json = :c WHERE id = :m"),
                {"c": json.dumps(fixes, ensure_ascii=False), "m": message_id},
            )
        used = 0
        for lemma in review.words_used[:30]:
            lexeme = conn.execute(
                text(
                    "SELECT l.id FROM lexemes l JOIN user_words w ON w.lexeme_id = l.id "
                    "WHERE l.language_code = :l AND l.lemma = :w"
                ),
                {"l": lang, "w": lemma.strip()},
            ).scalar()
            if lexeme:
                conn.execute(text("INSERT INTO word_events (lexeme_id, event) VALUES (:x, 'tutor_used_ok')"), {"x": lexeme})
                used += 1
        summary = review.summary.strip()
        if review.strengths:
            summary += "\n\nWhat went well: " + "; ".join(x.strip() for x in review.strengths if x.strip())
        conn.execute(
            text("UPDATE tutor_sessions SET summary_md = :s, postprocessed = 1 WHERE id = :id"), {"s": summary, "id": session_id}
        )
    return {"session_id": session_id, "corrections": sum(len(v) for v in by_message.values()), "words_used": used}


def grammar_overview(conn: Connection, lang: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            "SELECT g.key, g.title, g.level, u.status, u.errors, u.successes, u.mastery, u.last_error_at, "
            "(SELECT e.original_text || ' → ' || e.corrected_text FROM grammar_evidence e WHERE e.grammar_point_id = g.id "
            " ORDER BY e.created_at DESC LIMIT 1) FROM grammar_points g JOIN user_grammar u ON u.grammar_point_id = g.id "
            "WHERE g.language_code = :l ORDER BY u.mastery, u.errors DESC"
        ),
        {"l": lang},
    ).all()
    keys = ("key", "title", "level", "status", "errors", "successes", "mastery", "last_error_at", "example")
    return [dict(zip(keys, r)) for r in rows]


def recent_items(conn: Connection, lang: str, limit: int = 10) -> list[dict[str, Any]]:
    """The videos and texts you watched or read most recently: topics for a conversation."""
    from app.services.content import READ_TYPES, WATCH_TYPES

    types = ", ".join(f"'{t}'" for t in WATCH_TYPES + READ_TYPES)
    rows = conn.execute(
        text(
            "SELECT ci.id, ci.title, ci.type, ci.creator, MAX(COALESCE((SELECT MAX(s.started_at) FROM activity_sessions s "
            "WHERE s.content_item_id = ci.id), ''), COALESCE(ci.last_opened_at, '')) AS last_at "
            f"FROM content_items ci WHERE ci.language_code = :l AND ci.type IN ({types}) "
            "AND (ci.last_opened_at IS NOT NULL OR EXISTS (SELECT 1 FROM activity_sessions s WHERE s.content_item_id = ci.id)) "
            "ORDER BY last_at DESC, ci.id DESC LIMIT :n"
        ),
        {"l": lang, "n": limit},
    ).all()
    return [
        {"id": r[0], "title": r[1], "type": r[2], "creator": r[3], "last_at": r[4] or None,
         "kind": "video" if r[2] in WATCH_TYPES else "reading"}
        for r in rows
    ]
