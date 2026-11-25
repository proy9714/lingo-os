"""The grammar references load, are well-formed, and link the tutor's notes to the right sections."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.services import grammar


@pytest.mark.parametrize("lang", ["de", "es", "ja"])
def test_every_language_has_a_well_formed_reference(lang: str) -> None:
    ref = grammar.reference(lang)
    sections = ref["sections"]
    assert len(sections) >= 20
    assert [s["number"] for s in sections] == list(range(1, len(sections) + 1))
    assert {s["kind"] for s in sections} >= {"structure", "verbs", "contrast", "summary"}
    for section in sections:
        assert section["title"] and (section["tables"] or section["examples"] or section["points"])
        for example in section["examples"]:
            assert example["text"] and example["translation"]
    if lang == "ja":  # Japanese examples carry a kana reading
        assert all(e["reading"] for s in sections for e in s["examples"])


def test_reference_endpoint_links_tutor_notes(client) -> None:
    engine = client.app.state.engine
    with engine.begin() as conn:
        point = conn.execute(
            text("INSERT INTO grammar_points (language_code, key, title, origin) VALUES ('de', 'de.dative_after_mit', 'dative after mit', 'llm')")
        ).lastrowid
        conn.execute(
            text("INSERT INTO user_grammar (grammar_point_id, status, mastery, errors) VALUES (:p, 'practicing', 0.3, 2)"), {"p": point}
        )
    body = client.get("/api/tutor/reference/de").json()
    assert body["title"] == "German grammar" and len(body["sections"]) >= 20
    spot = body["weak_spots"][0]
    assert spot["title"] == "dative after mit"
    assert "akk-dat" in spot["sections"] or "cases" in spot["sections"]
    assert client.get("/api/tutor/reference/xx").status_code in (404, 422)


def test_every_grammar_reference_loads_and_is_well_formed() -> None:
    from pathlib import Path

    from app.services import grammar

    files = sorted(Path(grammar.__file__).resolve().parents[1].joinpath("grammar").glob("*.yaml"))
    assert {f.stem for f in files} >= {"de", "es", "ja", "fr", "it", "pt", "ru", "ko", "zh", "hi", "bn", "ar"}
    for path in files:
        ref = grammar.reference(path.stem)
        assert ref["title"] and len(ref["sections"]) >= 10, path.stem
        ids = [s["id"] for s in ref["sections"]]
        assert len(ids) == len(set(ids)), path.stem
        assert any(s["kind"] == "summary" for s in ref["sections"]), path.stem
        for section in ref["sections"]:
            assert section["kind"] in {"structure", "verbs", "contrast", "summary"}, (path.stem, section["id"])
            for example in section["examples"]:
                assert example["text"] and example["translation"], (path.stem, section["id"])
