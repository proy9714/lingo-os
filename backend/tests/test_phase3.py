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
