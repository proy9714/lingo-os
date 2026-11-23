"""Tokens annotated with your knowledge: the data behind clickable, coloured text."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection

from app.engine.profile import get_profile
from app.engine.vocab_model import DEFAULT_K, p_known
from app.languages import analyze
from app.languages.frequency import rank_of
from app.services import vocab

MAX_CHARS = 20_000


def annotate(conn: Connection, lang: str, text: str) -> dict[str, Any]:
    tokens, sentences = analyze(lang, text)
    profile = get_profile(conn, lang) or {"r50": 500.0, "k": DEFAULT_K}
    known = vocab.states(conn, lang, [(t.lemma, t.reading) for t in tokens if t.is_word])

    out: list[dict[str, Any]] = []
    learnable = 0
    p_total = 0.0
    new_keys: set[str] = set()
    for token in tokens:
        rank = best_rank(lang, token.lemma, token.display, token.lookup_forms) if token.is_word else None
        state = known.get(token.key) if token.is_word else None
        if not token.is_word:
            status, p = "none", None
        elif state:
            p = 1.0 if state["status"] == "ignored" else state["p_known"]
            status = state["status"]
            if status == "seen":
                status = "new" if p < 0.5 else "likely"
        elif token.learnable:
            p = p_known(rank, profile["r50"], profile["k"])
            status = "likely" if p >= 0.5 else "new"
        else:
            status, p = "none", 1.0  # function words, names, numbers: never highlighted

        if token.learnable and token.pos != "PROPN":
            learnable += 1
            p_total += p if p is not None else 1.0
            if status in {"new", "learning"}:
                new_keys.add(token.key)

        out.append(
            {
                "start": token.start,
                "end": token.end,
                "word": token.is_word,
                "lemma": token.lemma,
                "display": token.display,
                "reading": token.reading,
                "pos": token.pos,
                "learnable": token.learnable,
                "forms": list(token.lookup_forms),
                "rank": rank,
                "status": status,
                "p": round(p, 3) if p is not None else None,
            }
        )

    return {
        "language": lang,
        "tokens": out,
        "sentences": [{"start": s.start, "end": s.end} for s in sentences],
        "summary": {
            "words": learnable,
            "known_share": round(p_total / learnable, 3) if learnable else None,
            "new_words": len(new_keys),
            "profile_measured": bool(profile.get("measured")),
        },
    }


def best_rank(lang: str, lemma: str, display: str, forms: tuple[str, ...] | list[str]) -> int | None:
    """Rank of the lemma itself; other forms only when the lemma is not in the frequency list."""
    return rank_of(lang, lemma) or rank_of(lang, display) or rank_of(lang, *forms)


def word_info(conn: Connection, lang: str, lemma: str, reading: str, forms: list[str]) -> dict[str, Any]:
    profile = get_profile(conn, lang) or {"r50": 500.0, "k": DEFAULT_K}
    rank = best_rank(lang, lemma, lemma, forms)
    return {"rank": rank, "model_p": round(p_known(rank, profile["r50"], profile["k"]), 3)}
