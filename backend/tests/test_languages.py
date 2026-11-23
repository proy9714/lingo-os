from __future__ import annotations

from app.languages import analyze


def _words(lang: str, text: str) -> dict[str, tuple[str, str, bool]]:
    tokens, _ = analyze(lang, text)
    return {t.text: (t.lemma, t.reading, t.learnable) for t in tokens if t.is_word}


def test_german_separable_verbs_and_modal_fixes() -> None:
    words = _words("de", "Ich rufe dich morgen an. Man muss sich durchsetzen.")
    assert words["rufe"][0] == "anrufen"
    assert words["an"][0] == "anrufen"  # the particle points at the same verb
    assert words["muss"][0] == "müssen"
    assert words["dich"][2] is False  # pronouns are never highlighted


def test_german_quantifiers_get_dictionary_lemmas() -> None:
    words = _words("de", "Viele Leute und alle Kinder, einige Nachbarn.")
    assert (words["Viele"][0], words["alle"][0], words["einige"][0]) == ("viel", "all", "einig")


def test_german_sentences_have_offsets() -> None:
    text = "Die Mieten sind gestiegen. Wir suchen eine WG."
    tokens, sentences = analyze("de", text)
    assert [text[s.start : s.end] for s in sentences] == ["Die Mieten sind gestiegen.", "Wir suchen eine WG."]
    mieten = next(t for t in tokens if t.text == "Mieten")
    assert text[mieten.start : mieten.end] == "Mieten" and mieten.lemma == "Miete"


def test_spanish_attached_pronouns() -> None:
    words = _words("es", "Dámelo, por favor. Quiero aprovecharlo.")
    assert words["Dámelo"][0] == "dar"
    assert words["aprovecharlo"][0] == "aprovechar"


def test_japanese_groups_verbs_with_auxiliaries() -> None:
    tokens, sentences = analyze("ja", "急がないと間に合わないよ！彼はご飯を食べている。")
    words = {t.text: t for t in tokens if t.is_word}
    assert words["間に合わない"].lemma == "間に合う" and words["間に合わない"].reading == "まにあう"
    assert words["食べている"].lemma == "食べる"
    assert words["ご飯"].display == "ご飯"  # written form kept for display
    assert words["は"].learnable is False
    assert len(sentences) == 2
