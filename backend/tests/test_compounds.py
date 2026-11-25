"""German compounds the dictionary doesn't list are shown as their parts."""

from __future__ import annotations

import json

from sqlalchemy import text

from app.db.engine import make_engine
from app.dictionary.lookup import compound_parts, split_compound

WORDS = {
    "Weihnachtsmarkt": "Christmas market", "Besucher": "visitor", "Hund": "dog", "Hütte": "hut", "Fahrrad": "bicycle",
    "Weg": "path", "weg": "away", "Arbeit": "work", "Zeit": "time", "Kindergarten": "nursery school", "Platz": "square",
}
FORMS = {"Hunde": "Hund"}


def _dictionary(cfg) -> None:
    engine = make_engine(cfg.dict_db_path)
    with engine.begin() as conn:
        dict_id = conn.execute(
            text("INSERT INTO dictionaries (language_code, name, kind, format) VALUES ('de', 'test', 'term', 'yomitan')")
        ).lastrowid
        for term, gloss in WORDS.items():
            conn.execute(text("INSERT INTO dict_terms (dictionary_id, term, glossary_json) VALUES (:d, :t, :g)"),
                         {"d": dict_id, "t": term, "g": json.dumps({"g": [gloss]})})
        for term, lemma in FORMS.items():
            conn.execute(text("INSERT INTO dict_terms (dictionary_id, term, glossary_json) VALUES (:d, :t, :g)"),
                         {"d": dict_id, "t": term, "g": json.dumps({"f": [{"lemma": lemma, "rules": ["plural"]}]})})
    engine.dispose()


def test_compounds_split_into_dictionary_words(client) -> None:
    cfg = client.app.state.cfg
    _dictionary(cfg)
    engine = make_engine(cfg.dict_db_path)
    with engine.connect() as conn:
        assert split_compound(conn, "de", "Weihnachtsmarktbesucher") == ["Weihnachtsmarkt", "Besucher"]
        assert split_compound(conn, "de", "Hundehütte") == ["Hund", "Hütte"]  # the word, not its plural Hunde
        assert split_compound(conn, "de", "Arbeitszeit") == ["Arbeit", "Zeit"]  # linking -s-
        assert split_compound(conn, "de", "Fahrradweg") == ["Fahrrad", "Weg"]  # the noun, not 'weg'
        assert split_compound(conn, "de", "Kindergartenplatz") == ["Kindergarten", "Platz"]
        assert split_compound(conn, "de", "Arbeit") is None and split_compound(conn, "es", "Arbeitszeit") is None
        assert compound_parts(conn, "de", "Hundehütte")[0] == {"part": "Hund", "gloss": "dog", "term": "Hund"}
    engine.dispose()
    body = client.post("/api/nlp/lookup", json={"lang": "de", "lemma": "Weihnachtsmarktbesucher", "record": False}).json()
    assert [p["term"] for p in body["compound"]] == ["Weihnachtsmarkt", "Besucher"]
