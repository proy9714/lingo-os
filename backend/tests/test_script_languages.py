"""Hindi, Bengali and Arabic: words, dictionary forms, right-to-left, Level Lab and search checks."""

from __future__ import annotations

import pytest

from app.languages import registry
from app.languages.detect import looks_like
from app.languages.script_pack import ScriptPack, arabic_forms, strip_marks
from app.level.dictation import score
from app.level.dictation_sentences import SENTENCES


@pytest.mark.parametrize(
    ("code", "text", "words"),
    [
        ("hi", "मैं कल बाज़ार गया था।", ["मैं", "कल", "बाज़ार", "गया", "था"]),
        ("bn", "আমি কাল বাজারে গিয়েছিলাম।", ["আমি", "কাল", "বাজারে", "গিয়েছিলাম"]),
        ("ar", "ذهبتُ إلى السوقِ أمس.", ["ذهبتُ", "إلى", "السوقِ", "أمس"]),
    ],
)
def test_words_and_sentences(code: str, text: str, words: list[str]) -> None:
    tokens, sentences = ScriptPack(code).analyze(text)
    assert [t.text for t in tokens if t.is_word] == words
    assert len(sentences) == 1
    assert all(text[t.start : t.end] == t.text for t in tokens)
    function_words = {"hi": "था", "bn": "আমি", "ar": "إلى"}[code]
    assert not next(t for t in tokens if t.text == function_words).learnable  # common words aren't coloured


def test_arabic_is_looked_up_without_vowel_marks_or_glued_prefixes() -> None:
    assert strip_marks("ar", "السُّوقِ") == "السوق"
    assert strip_marks("hi", "बाज़ार") == "बाज़ार"
    forms = arabic_forms("والناسُ")
    assert forms[0] == "والناس" and "الناس" in forms and "ناس" in forms
    assert arabic_forms("أمس")[-1] == "امس"  # hamza seat folded too


def test_dictionary_forms_come_from_the_resolver(monkeypatch) -> None:
    import app.languages as languages

    calls = []

    def resolver(code, surface, lemma, others=(), guesses=frozenset()):
        calls.append((surface, lemma, others))
        return "ناس" if "ناس" in others else None

    languages.set_lemma_resolver(resolver)
    try:
        tokens, _ = languages.analyze("ar", "والناسُ كثيرون")
        assert tokens[0].lemma == "ناس" and "ناس" in tokens[0].lookup_forms
        assert calls[0][0] == "والناس"  # the surface is compared without vowel marks
    finally:
        languages.set_lemma_resolver(None)


def test_catalogue_offers_them() -> None:
    for code in ("hi", "bn", "ar"):
        assert code in registry.AVAILABLE and registry.spec(code).dictionary_lemmas
    assert registry.spec("ar").direction == "rtl"


def test_level_lab_and_search_checks() -> None:
    for code in ("hi", "bn", "ar"):
        assert set(SENTENCES[code]) == {"A1", "A2", "B1", "B2", "C1"}
    assert score("ar", "أشرب القهوة كل صباح.", "أشربُ القهوةَ كلَّ صباح") == 1.0
    assert score("hi", "मैं रोज़ सुबह चाय पीता हूँ।", "मैं रोज सुबह चाय पीता हूं") == 1.0
    hindi = "भारत सरकार ने सोमवार को घोषणा की कि नए नियम अगले साल से लागू होंगे। यह बहुत से लोगों के लिए अच्छी खबर है, लेकिन सभी के लिए नहीं।"
    persian = "دولت روز دوشنبه اعلام کرد که قوانین جدید از سال آینده اجرا می شود. این خبر خوبی برای بسیاری از مردم است، اما نه برای همه."
    assert looks_like("hi", hindi) and not looks_like("bn", hindi) and not looks_like("ar", persian)
