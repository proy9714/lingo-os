"""Furigana: readings over the kanji only, from the words as written."""

from __future__ import annotations

from app.languages import analyze
from app.languages.ja import furigana


def test_readings_sit_over_kanji_only() -> None:
    assert furigana("食べさせた", "たべさせた") == (("食", "た"), ("べさせた", ""))
    assert furigana("お茶", "おちゃ") == (("お", ""), ("茶", "ちゃ"))
    assert furigana("今日", "きょう") == (("今日", "きょう"),)
    assert furigana("ありがとう", "ありがとう") == ()  # no kanji, nothing to add
    assert furigana("一人", "ひとり") == (("一人", "ひとり"),)


def test_tokens_carry_the_reading_as_written_not_the_dictionary_form(client) -> None:
    tokens, _ = analyze("ja", "昨日は食べさせられた。")
    eaten = next(t for t in tokens if t.text.startswith("食"))
    assert eaten.ruby[0] == ("食", "た") and eaten.reading == "たべる"
    body = client.post("/api/nlp/tokenize", json={"lang": "ja", "text": "昨日は食べさせられた。"}).json()
    rubies = [t.get("ruby") for t in body["tokens"] if t.get("ruby")]
    assert ["昨日", "きのう"] in rubies[0] and rubies[1][0] == ["食", "た"]
