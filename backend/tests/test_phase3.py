from __future__ import annotations

import io
import zipfile
from pathlib import Path

from sqlalchemy import text

from app.ingest.documents import html_to_section, parse_epub, parse_text
from app.services.recommend import up_next


def _epub(path: Path) -> Path:
    container = (
        '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>'
    )
    opf = (
        '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Kleines Buch</dc:title><dc:creator>Anna</dc:creator>'
        "<dc:language>de</dc:language></metadata>"
        '<manifest><item id="c1" href="ch1.xhtml" media-type="application/xhtml+xml"/>'
        '<item id="nav" href="nav.xhtml" properties="nav" media-type="application/xhtml+xml"/></manifest>'
        '<spine><itemref idref="c1"/></spine></package>'
    )
    chapter = (
        "<html><body><h1>Kapitel 1</h1><p>Am Samstag gehe ich auf den Markt.</p>"
        "<p>Dort kaufe ich <b>frisches</b> Obst.</p><p><ruby>漢字<rt>かんじ</rt></ruby>です。</p></body></html>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("OEBPS/content.opf", opf)
        archive.writestr("OEBPS/ch1.xhtml", chapter)
    path.write_bytes(buffer.getvalue())
    return path


def test_epub_parsing(tmp_path: Path) -> None:
    doc = parse_epub(_epub(tmp_path / "book.epub"))
    assert (doc.title, doc.author, doc.language) == ("Kleines Buch", "Anna", "de")
    section = doc.sections[0]
    assert section.title == "Kapitel 1"
    assert section.paragraphs[1:] == ["Am Samstag gehe ich auf den Markt.", "Dort kaufe ich frisches Obst.", "漢字です。"]


def test_html_blocks_and_ruby() -> None:
    section = html_to_section("<div><p>Eins.</p><p>Zwei <i>drei</i>.</p></div><p><ruby>東京<rt>とうきょう</rt></ruby></p>")
    assert section.paragraphs == ["Eins.", "Zwei drei.", "東京"]


def test_upload_epub_then_read_pages(client, tmp_path: Path) -> None:
    path = _epub(tmp_path / "book.epub")
    with path.open("rb") as fh:
        response = client.post("/api/content/upload", data={"lang": "de"}, files={"file": ("book.epub", fh, "application/epub+zip")})
    assert response.status_code == 201, response.text
    item = response.json()
    assert item["type"] == "epub" and item["title"] == "Kleines Buch" and item["analysis_status"] == "done"

    pages = client.get(f"/api/content/{item['id']}/pages").json()
    assert pages["total"] == 1
    page = client.get(f"/api/content/{item['id']}/page/1").json()
    assert page["title"] == "Kapitel 1"
    first = page["paragraphs"][1]
    assert first["text"] == "Am Samstag gehe ich auf den Markt."
    assert any(t["display"] == "Markt" and t["learnable"] for t in first["tokens"])
    shelf = client.get("/api/content", params={"lang": "de", "shelf": "read"}).json()
    assert [i["id"] for i in shelf["items"]] == [item["id"]]


def test_wrong_upload_type_is_rejected(client) -> None:
    response = client.post("/api/content/upload", data={"lang": "de"}, files={"file": ("x.docx", b"hi", "application/octet-stream")})
    assert response.status_code == 422


def test_saved_text_and_page_progress(client) -> None:
    item = client.post("/api/content/text", json={"lang": "es", "title": "Nota", "text": "Hola.\n\nMe llamo Ana y vivo en Madrid."}).json()
    assert item["type"] == "text"
    client.post(f"/api/content/{item['id']}/read-progress", json={"page": 1, "total": 1})
    refreshed = client.get(f"/api/content/{item['id']}").json()
    assert refreshed["status"] == "finished" and refreshed["progress"] == 1.0


def test_parse_text_splits_paragraphs() -> None:
    assert parse_text("T", "Eins.\n\nZwei.\nDrei.").sections[0].paragraphs == ["Eins.", "Zwei.", "Drei."]


def test_up_next_applies_variety_rules(client) -> None:
    engine = client.app.state.engine
    with engine.begin() as conn:
        for i in range(8):
            item_id = conn.execute(
                text(
                    "INSERT INTO content_items (language_code, type, title, creator, origin, source, external_id, analysis_status) "
                    "VALUES ('de', 'youtube', :t, 'Same Channel', 'user_added', 'youtube', :e, 'done')"
                ),
                {"t": f"Video {i}", "e": f"vid{i:08d}xyz"},
            ).lastrowid
            conn.execute(
                text(
                    "INSERT INTO content_scores (content_item_id, profile_version, coverage, expected_unknown, i1_score, band) "
                    "VALUES (:id, 1, 0.92, 10, :s, 'i_plus_1')"
                ),
                {"id": item_id, "s": 0.9 - i * 0.01},
            )
        result = up_next(conn, "de", 5)
    assert result["available"] == 8
    assert len(result["picks"]) == 5  # the creator limit is relaxed only to fill the list
    assert result["picks"][0]["reasons"][0] == "≈ 92% known"


def test_recommend_endpoint(client) -> None:
    body = client.get("/api/recommend", params={"lang": "de"}).json()
    assert body["picks"] == [] and body["available"] == 0


def test_article_needs_a_url(client) -> None:
    assert client.post("/api/content/article", json={"lang": "de", "url": "not a url"}).status_code == 422


def test_history_fetch_can_be_queued(client) -> None:
    response = client.post("/api/content/history/fetch", json={})
    assert response.status_code == 202 and response.json()["job_id"] > 0


def test_up_next_never_suggests_watched_videos_or_finished_items(client) -> None:
    engine = client.app.state.engine
    with engine.begin() as conn:
        ids = {}
        for name, kind, status, progress in [
            ("watched in the app", "youtube", "finished", 0.95),
            ("left after a third", "youtube", "in_progress", 0.3),
            ("from the tracker CSV", "youtube", "library", 0.0),
            ("new video", "youtube", "candidate", 0.0),
            ("finished book", "epub", "finished", 1.0),
            ("book in progress", "epub", "in_progress", 0.4),
        ]:
            ids[name] = conn.execute(
                text(
                    "INSERT INTO content_items (language_code, type, title, origin, source, external_id, status, progress, "
                    "analysis_status) VALUES ('de', :k, :t, 'user_added', 'x', :t, :s, :p, 'done')"
                ),
                {"k": kind, "t": name, "s": status, "p": progress},
            ).lastrowid
            conn.execute(
                text("INSERT INTO content_scores (content_item_id, profile_version, coverage, expected_unknown, i1_score, band) VALUES (:i, 1, 0.92, 10, 0.8, 'i_plus_1')"),
                {"i": ids[name]},
            )
        for name, tracking in [("watched in the app", "auto"), ("left after a third", "auto"), ("from the tracker CSV", "import")]:
            conn.execute(
                text(
                    "INSERT INTO activity_sessions (language_code, activity, modality, tracking, started_at, active_seconds, "
                    "content_item_id) VALUES ('de', 'video', 'listening', :tr, '2026-11-01T10:00:00.000Z', 600, :i)"
                ),
                {"tr": tracking, "i": ids[name]},
            )
        picks = up_next(conn, "de", 10)["picks"]
    # a video counts as watched only when 90% of it played (or it was marked, or the tracker lists it)
    assert {p["title"] for p in picks} == {"new video", "book in progress", "left after a third"}
    assert next(p for p in picks if p["title"] == "book in progress")["reasons"][-1] == "continue where you left off"


def test_article_pictures_are_placed_between_paragraphs_and_junk_is_dropped() -> None:
    from app.ingest.documents import article_images

    paragraphs = ["Le maire a présenté le nouveau projet ce matin devant la presse.", "Les travaux commenceront en mars et dureront deux ans au total."]
    markdown = (
        "![Jean Dupont](https://cdn.example/avatars/jean.png)\n\nJean Dupont\n\n"
        "Le maire a présenté le nouveau projet ce matin devant la presse.\n\n"
        "![Le futur parc](https://cdn.example/photos/parc.jpg)\n\n"
        "Les travaux commenceront en mars et dureront deux ans au total.\n\n"
        "![Logo](https://cdn.example/logo.svg)"
    )
    assert article_images(markdown, paragraphs, lead=None) == [(0, "https://cdn.example/photos/parc.jpg")]
    # the lead picture is shown at the top already: not repeated in the text
    assert article_images(markdown, paragraphs, lead="https://cdn.example/photos/parc.jpg") == []


def test_pictures_become_chunks_without_text(client) -> None:
    from app.ingest.documents import Document, Section
    from app.services import reading

    doc = Document("Titel", None, "de", [Section(None, ["Erster Absatz mit ein paar Wörtern.", "Zweiter Absatz."])],
                   images=[(0, "https://cdn.example/bild.jpg")])
    with client.app.state.engine.begin() as conn:
        item_id, _ = reading.import_document(conn, client.app.state.cfg, "de", doc, item_type="article", source="web",
                                             source_url="https://example.de/a")
        page = reading.page(conn, item_id, 1)
    kinds = [p.get("image") or p["text"][:6] for p in page["paragraphs"]]
    assert kinds == ["Erster", "https://cdn.example/bild.jpg", "Zweite"]
    assert page["paragraphs"][1]["tokens"] == []
