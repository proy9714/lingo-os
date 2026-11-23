from __future__ import annotations

from pathlib import Path

from app.db import migrate
from app.db.engine import make_engine
from app.dictionary.lookup import display_gloss, lookup
from app.dictionary.yomitan import import_dictionary, list_dictionaries
from yomitan_fixture import GERMAN_ROWS, JAPANESE_ROWS, make_zip


def _dict_engine(tmp_path: Path):
    db = tmp_path / "dictionaries.db"
    migrate.apply_migrations(db, "dict")
    return make_engine(db)


def test_import_and_lookup(tmp_path: Path) -> None:
    engine = _dict_engine(tmp_path)
    de_zip = make_zip(tmp_path / "de.zip", "de", GERMAN_ROWS, "wty-de-en")
    ja_zip = make_zip(tmp_path / "ja.zip", "ja", JAPANESE_ROWS, "Jitendex.org [2026-11-23]")
    with engine.begin() as conn:
        result = import_dictionary(conn, de_zip)
        assert (result["entries"], result["inflected_forms"]) == (5, 2)
        import_dictionary(conn, ja_zip)
        names = {d["name"] for d in list_dictionaries(conn)}
        assert names == {"wty-de-en", "Jitendex.org"}  # release date stripped from the title

        miete = lookup(conn, "de", ["Miete"])["entries"][0]
        assert miete["glosses"] == ["rent"] and miete["note"].startswith("Miete f")
        assert "n" in miete["pos"]

        # An inflected form is followed to its lemma.
        via = lookup(conn, "de", ["muss"])
        assert via["inflections"][0]["lemma"] == "müssen"
        assert via["entries"][0]["term"] == "müssen" and via["entries"][0]["via_inflection"]

        # The clicked form is explained only relative to the lemma it belongs to.
        explained = lookup(conn, "de", ["müssen", "muss"])
        assert explained["entries"][0]["term"] == "müssen" and explained["inflections"][0]["form"] == "muss"
        assert lookup(conn, "de", ["anrufen", "Mieten"])["inflections"] == []  # Mieten→Miete is unrelated

        # Lemma first; other forms only when the lemma has no entry.
        assert lookup(conn, "de", ["anrufen", "Mieten"])["entries"][0]["term"] == "anrufen"
        assert lookup(conn, "de", ["Unbekannt", "Mieten"])["entries"][0]["term"] == "Miete"

        train = lookup(conn, "ja", ["電車"], reading="でんしゃ")["entries"][0]
        assert train["glosses"] == ["train", "electric train"] and train["pos"] == ["noun"]


def test_reimport_replaces_the_old_copy(tmp_path: Path) -> None:
    engine = _dict_engine(tmp_path)
    path = make_zip(tmp_path / "de.zip", "de", GERMAN_ROWS, "wty-de-en")
    with engine.begin() as conn:
        import_dictionary(conn, path)
        import_dictionary(conn, path)
        assert len(list_dictionaries(conn)) == 1
        assert len(lookup(conn, "de", ["Miete"])["entries"]) == 1


def test_display_gloss_strips_usage_labels() -> None:
    assert display_gloss("vt to make use of, to make the most of") == "to make use of, to make the most of"
    assert display_gloss("to make use of, to make the most of, to get the most out of", 30) == "to make use of"
