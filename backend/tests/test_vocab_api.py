from __future__ import annotations

from pathlib import Path

import pytest

from app.db.engine import make_engine
from app.dictionary.yomitan import import_dictionary
from yomitan_fixture import GERMAN_ROWS, make_zip


@pytest.fixture
def with_dictionary(client, cfg, tmp_path: Path):
    path = make_zip(tmp_path / "de.zip", "de", GERMAN_ROWS, "wty-de-en")
    with make_engine(cfg.dict_db_path).begin() as conn:
        import_dictionary(conn, path)
    return client


def test_tokenize_marks_status_and_summarises(client) -> None:
    body = client.post("/api/nlp/tokenize", json={"lang": "de", "text": "Die Mieten sind gestiegen."}).json()
    words = {t["display"]: t for t in body["tokens"] if t["word"]}
    assert words["Miete"]["learnable"] and words["Miete"]["status"] in {"new", "likely"}
    assert words["der"]["status"] == "none"  # articles are never highlighted
    assert body["summary"]["words"] >= 2
    assert body["sentences"] == [{"start": 0, "end": 26}]


def test_lookup_records_evidence_and_shows_entries(with_dictionary) -> None:
    client = with_dictionary
    body = client.post("/api/nlp/lookup", json={"lang": "de", "lemma": "Miete", "forms": ["Mieten"], "pos": "NOUN"}).json()
    assert body["entries"][0]["glosses"] == ["rent"]
    assert body["state"]["status"] == "seen" and body["state"]["lookups"] == 1
    again = client.post("/api/nlp/lookup", json={"lang": "de", "lemma": "Miete", "forms": []}).json()
    assert again["state"]["lookups"] == 2 and again["state"]["p_known"] <= body["state"]["p_known"]
    quiet = client.post("/api/nlp/lookup", json={"lang": "de", "lemma": "Miete", "record": False}).json()
    assert quiet["state"]["lookups"] == 2


def test_lookup_without_dictionary_says_so(client) -> None:
    body = client.post("/api/nlp/lookup", json={"lang": "es", "lemma": "andén"}).json()
    assert body["entries"] == [] and body["missing_dictionary"] is True


def test_save_with_context_then_browse_and_edit(client) -> None:
    saved = client.post(
        "/api/vocab/status",
        json={
            "lang": "de",
            "lemma": "Miete",
            "pos": "NOUN",
            "status": "learning",
            "save": True,
            "context": {"sentence": "Die Mieten sind gestiegen.", "surface": "Mieten", "locator": "paste"},
        },
    ).json()
    assert saved["status"] == "learning" and saved["saved"] and saved["contexts"] == 1

    listing = client.get("/api/vocab/words", params={"lang": "de", "status": "saved"}).json()
    assert listing["total"] == 1 and listing["items"][0]["latest_sentence"] == "Die Mieten sind gestiegen."

    word_id = saved["lexeme_id"]
    patched = client.patch(f"/api/vocab/words/{word_id}", json={"status": "known", "note": "Kaltmiete vs Warmmiete"}).json()
    assert patched["status"] == "known" and patched["user_note"] == "Kaltmiete vs Warmmiete"
    detail = client.get(f"/api/vocab/words/{word_id}").json()
    assert detail["contexts_list"][0]["surface"] == "Mieten"
    assert client.get("/api/vocab/summary", params={"lang": "de"}).json()["known"] == 1

    # A known word now shows as known when the text is tokenized again.
    tokens = client.post("/api/nlp/tokenize", json={"lang": "de", "text": "Die Miete ist hoch."}).json()["tokens"]
    assert next(t for t in tokens if t["display"] == "Miete")["status"] == "known"


def test_bad_status_is_rejected(client) -> None:
    response = client.post("/api/vocab/status", json={"lang": "de", "lemma": "x", "status": "due"})
    assert response.status_code == 422
