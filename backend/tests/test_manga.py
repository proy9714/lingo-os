from __future__ import annotations

import json
import struct
import zipfile
import zlib
from pathlib import Path

from app.ingest.mokuro import image_size, natural_key
from app.services.manga import inbox_root


def png(width: int, height: int) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    raw = b"".join(b"\x00" + b"\xff" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def make_mokuro_volume(folder: Path, name: str = "Vol 01") -> Path:
    images = folder / name
    images.mkdir(parents=True)
    for n in (1, 2):
        (images / f"p{n:03d}.png").write_bytes(png(20, 30))
    data = {
        "title": "よつばと",
        "volume": name,
        "volume_uuid": f"uuid-{name}",
        "pages": [
            {
                "img_path": "p001.png", "img_width": 1000, "img_height": 1500,
                "blocks": [
                    {"box": [600, 100, 700, 400], "vertical": True, "font_size": 30,
                     "lines": ["今日は", "公園に行きます。"], "lines_coords": [[[0, 0]] * 4, [[0, 0]] * 4]},
                    {"box": [100, 900, 300, 1000], "vertical": False, "font_size": 24, "lines": ["パンを買う。"]},
                ],
            },
            {"img_path": "p002.png", "img_width": 1000, "img_height": 1500,
             "blocks": [{"box": [50, 50, 150, 300], "vertical": True, "lines": ["公園で遊ぶ。"]}]},
        ],
    }
    path = folder / f"{name}.mokuro"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_image_size_and_natural_sort(tmp_path: Path) -> None:
    path = tmp_path / "a.png"
    path.write_bytes(png(37, 51))
    assert image_size(path) == (37, 51)
    assert sorted(["p10", "p9", "p1"], key=natural_key) == ["p1", "p9", "p10"]


def test_scan_imports_a_mokuro_volume_and_serves_pages(client, cfg) -> None:
    make_mokuro_volume(inbox_root(cfg))
    result = client.post("/api/manga/scan").json()
    assert [r["status"] for r in result["results"]] == ["imported"]
    item_id = result["results"][0]["item_id"]

    # the inbox is left clean; nothing is deleted, originals go to _imported
    leftovers = [p.name for p in inbox_root(cfg).iterdir()]
    assert leftovers == [] or leftovers == ["_imported"]

    shelf = client.get("/api/content", params={"lang": "ja", "shelf": "manga"}).json()
    assert [i["id"] for i in shelf["items"]] == [item_id]
    item = shelf["items"][0]
    assert item["type"] == "manga_volume" and item["page_count"] == 2 and item["analysis_status"] == "done"

    page = client.get(f"/api/manga/{item_id}/page/1").json()
    assert (page["page"], page["pages"], page["width"], page["height"]) == (1, 2, 1000, 1500)
    first = page["blocks"][0]
    assert first["text"] == "今日は公園に行きます。" and first["vertical"] is True
    assert [line["start"] for line in first["lines"]] == [0, 3]
    assert any(t["display"] == "公園" for t in first["tokens"])
    image = client.get(f"/api/manga/{item_id}/image/2")
    assert image.status_code == 200 and image.content.startswith(b"\x89PNG")
    assert client.get(f"/api/manga/{item_id}/image/9").status_code == 404

    vocab = client.get(f"/api/manga/{item_id}/vocab").json()
    park = next(w for w in vocab["words"] if w["lemma"] == "公園")
    assert park["count"] == 2 and park["first_page"] == 1 and park["pages"] == 2

    # scanning again finds nothing new
    assert client.post("/api/manga/scan").json()["results"] == []


def test_a_duplicate_volume_is_moved_aside_not_reimported(client, cfg) -> None:
    make_mokuro_volume(inbox_root(cfg))
    client.post("/api/manga/scan")
    make_mokuro_volume(inbox_root(cfg))  # the same volume dropped in again
    second = client.post("/api/manga/scan").json()
    assert [r["status"] for r in second["results"]] == ["already in library"]
    assert client.post("/api/manga/scan").json()["results"] == []


def test_image_folder_without_ocr_and_cbz(client, cfg) -> None:
    folder = inbox_root(cfg) / "de" / "Meine Serie" / "Band 2"
    folder.mkdir(parents=True)
    for n in range(3):
        (folder / f"{n}.png").write_bytes(png(10, 16))
    archive = inbox_root(cfg) / "Flat.cbz"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("001.png", png(12, 18))
        zf.writestr("002.png", png(12, 18))
    results = client.post("/api/manga/scan").json()["results"]
    statuses = {r["title"]: r["status"] for r in results}
    assert statuses == {"Band 2": "imported (no OCR text yet)", "Flat": "imported (no OCR text yet)"}
    german = client.get("/api/content", params={"lang": "de", "shelf": "manga"}).json()["items"]
    assert german[0]["title"] == "Meine Serie · Band 2" and german[0]["analysis_status"] == "no_text"
    page = client.get(f"/api/manga/{german[0]['id']}/page/1").json()
    assert (page["width"], page["height"], page["ocr"], page["blocks"]) == (10, 16, "pending", [])
    assert client.post(f"/api/manga/{german[0]['id']}/ocr").status_code == 409  # mokuro not installed
    assert (archive.parent / "_imported" / "Flat.cbz").exists()


def test_correcting_an_ocr_block(client, cfg) -> None:
    make_mokuro_volume(inbox_root(cfg))
    item_id = client.post("/api/manga/scan").json()["results"][0]["item_id"]
    block = client.get(f"/api/manga/{item_id}/page/2").json()["blocks"][0]
    fixed = client.put(f"/api/manga/blocks/{block['id']}", json={"lines": ["公園で", "走る。"]}).json()
    assert fixed["text"] == "公園で走る。"
    again = client.get(f"/api/manga/{item_id}/page/2").json()["blocks"][0]
    assert again["corrected"] is True and [line["text"] for line in again["lines"]] == ["公園で", "走る。"]


def test_manga_counts_as_its_own_kind_in_up_next(client, cfg) -> None:
    make_mokuro_volume(inbox_root(cfg))
    client.post("/api/manga/scan")
    picks = client.get("/api/recommend", params={"lang": "ja"}).json()["picks"]
    assert [p["kind"] for p in picks] == ["manga"]
