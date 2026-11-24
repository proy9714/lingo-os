"""Adding languages from the catalogue, and the word splitters of the languages added in v0.3."""

from __future__ import annotations

import dataclasses
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import ROOT
from app.jobs import languages as language_jobs
from app.jobs.runner import JobContext
from app.languages import analyze, registry
from app.languages.spacy_pack import MODELS_DIR
from app.main import create_app

MODELS = ROOT / "data" / "models"


def _has_model(name: str) -> bool:
    return (MODELS / name / "config.cfg").exists()


def test_catalog_is_ordered_by_speakers(client) -> None:
    catalog = client.get("/api/languages/catalog").json()
    assert [c["code"] for c in catalog][:4] == ["zh", "hi", "es", "ar"]
    speakers = [c["speakers_millions"] for c in catalog]
    assert speakers == sorted(speakers, reverse=True) and len(catalog) == 12
    by_code = {c["code"]: c for c in catalog}
    assert by_code["de"]["added"] and not by_code["fr"]["added"]
    assert by_code["fr"]["available"] and not by_code["hi"]["available"]  # Hindi: a later version
    assert [v["id"] for v in by_code["pt"]["variants"]] == ["br", "pt"]
    assert by_code["ar"]["direction"] == "rtl"


def _fake_wheel(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("fr_core_news_sm/fr_core_news_sm-3.8.0/config.cfg", "[nlp]\nlang = \"fr\"\n")
        z.writestr("fr_core_news_sm/fr_core_news_sm-3.8.0/meta.json", "{}")
        z.writestr("fr_core_news_sm-3.8.0.dist-info/METADATA", "x")


def _fake_dictionary(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("index.json", json.dumps({"title": "Test French", "format": 3, "revision": "1", "sourceLanguage": "fr"}))
        z.writestr("term_bank_1.json", json.dumps([["chat", "", "n", "", 0, ["cat"], 1, ""]]))


def test_adding_a_language_downloads_it_then_adds_it(tmp_path, cfg, monkeypatch) -> None:
    def fake_download(url: str, target: Path, say) -> Path:  # noqa: ANN001
        target.parent.mkdir(parents=True, exist_ok=True)
        (_fake_wheel if url.endswith(".whl") else _fake_dictionary)(target)
        say(1.0)
        return target

    monkeypatch.setattr(language_jobs, "download", fake_download)
    with TestClient(create_app(cfg, run_jobs=False)) as client:
        added = client.post("/api/languages", json={"code": "fr", "variant": "ca"}).json()
        assert added == {"code": "fr", "added": False, "installing": True}
        assert "fr" not in [l["code"] for l in client.get("/api/languages").json()]  # not until it's ready
        assert next(c for c in client.get("/api/languages/catalog").json() if c["code"] == "fr")["installing"]

        app = client.app
        job_id = app.state.engine.connect().execute(
            __import__("sqlalchemy").text("SELECT id FROM jobs WHERE kind = 'install_language'")
        ).scalar()
        result = language_jobs.install_language(JobContext(app.state.engine, cfg, None, {"code": "fr", "variant": "ca"}))
        assert job_id and result["model"] == "fr_core_news_sm" and result["dictionary"] == "Test French"
        assert (cfg.data_dir / "models" / "fr_core_news_sm" / "config.cfg").exists()

        langs = {l["code"]: l for l in client.get("/api/languages").json()}
        assert list(langs) == ["de", "es", "ja", "fr"] and langs["fr"]["variant"] == "ca" and langs["fr"]["locale"] == "fr-CA"
        assert client.get("/api/settings").json()["goals"]["fr"] == 60

        # removing hides it (its data stays), and the active language moves on
        client.patch("/api/settings", json={"active_language": "fr"})
        assert client.delete("/api/languages/fr").json()["removed"]
        assert "fr" not in [l["code"] for l in client.get("/api/languages").json()]
        assert client.get("/api/settings").json()["active_language"] == "de"
        # adding it again is instant: everything is already here
        assert client.post("/api/languages", json={"code": "fr"}).json() == {"code": "fr", "added": True, "installing": False}


def test_last_language_cant_be_removed_and_unknown_ones_are_refused(client) -> None:
    for code in ("es", "ja"):
        assert client.delete(f"/api/languages/{code}").status_code == 200
    assert client.delete("/api/languages/de").status_code == 422
    assert client.post("/api/languages", json={"code": "xx"}).status_code == 422
    assert client.post("/api/languages", json={"code": "hi"}).status_code == 422  # not available yet
    assert client.post("/api/languages", json={"code": "pt", "variant": "zz"}).status_code == 422


def test_a_new_data_folder_starts_without_languages(cfg) -> None:
    fresh = dataclasses.replace(cfg, starting_languages=())
    with TestClient(create_app(fresh, run_jobs=False)) as client:
        assert client.get("/api/languages").json() == []
        assert client.get("/api/settings").json()["active_language"] is None


# ------------------------------------------------------------------ the new word splitters (need the downloaded models)


@pytest.fixture
def models():
    MODELS_DIR[:] = [MODELS]
    yield
    MODELS_DIR.clear()


@pytest.mark.parametrize(
    ("lang", "model", "text", "expected"),
    [
        ("fr", "fr_core_news_sm", "Je t'appellerai demain.", {"appellerai": "appeler"}),
        ("ru", "ru_core_news_sm", "Я позвоню тебе завтра.", {"позвоню": "позвонить"}),
        ("pt", "pt_core_news_sm", "Fizeram-no ontem.", {"Fizeram-no": "fazer"}),
        ("ko", "ko_core_news_sm", "우리는 밥을 먹었습니다.", {"먹었습니다": "먹다", "밥을": "밥"}),
    ],
)
def test_word_splitters(models, lang, model, text, expected) -> None:
    if not _has_model(model):
        pytest.skip(f"{model} isn't downloaded (add the language in the app to get it)")
    tokens, _ = analyze(lang, text)
    lemmas = {t.text: t.lemma for t in tokens}
    for word, lemma in expected.items():
        assert lemmas[word] == lemma


def test_chinese_words_get_pinyin(models) -> None:
    if not _has_model("zh_core_web_sm"):
        pytest.skip("zh_core_web_sm isn't downloaded")
    tokens, sentences = analyze("zh", "我明天给你打电话。")
    by_text = {t.text: t for t in tokens}
    assert by_text["打电话"].reading == "dǎ diàn huà" and by_text["打电话"].lemma == "打电话"
    assert len(sentences) == 1


def test_every_catalogue_language_has_what_the_app_needs() -> None:
    for spec in registry.CATALOG:
        assert spec.variants and spec.dictionary.url.startswith("https://")
        assert spec.default_variant.locale.split("-")[0] == spec.code
        if spec.code in registry.AVAILABLE and spec.pack in ("spacy", "ko", "zh"):
            assert spec.model is not None
