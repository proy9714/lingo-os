"""Manga library: import volumes from the inbox, serve pages with clickable text, volume vocabulary, OCR fixes.

Every imported volume is stored the same way, whatever it came as:
    data/library/manga/<lang>/<series>/<volume-id>/volume.mokuro   (OCR text, possibly with no blocks yet)
    data/library/manga/<lang>/<series>/<volume-id>/volume/          (page images)
Nothing is ever deleted from the inbox: imported originals move to data/inbox/manga/_imported/.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, text

from app.config import AppConfig
from app.ingest.mokuro import MangaError, Volume, block_text, find_volumes, read_image_folder, read_mokuro
from app.services.annotate import annotate_segments
from app.services.content import ContentError, analyze_item, get_item

INLINE_ANALYSIS_CHARS = 60_000


def inbox_root(cfg: AppConfig) -> Path:
    return cfg.data_dir / "inbox" / "manga"


def library_root(cfg: AppConfig) -> Path:
    return cfg.data_dir / "library" / "manga"


def _safe(name: str, limit: int = 60) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name).strip(" .")
    return cleaned[:limit] or "untitled"


def _volume_number(title: str) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)", title)
    return float(match.group(1)) if match else None


def ensure_inbox(cfg: AppConfig) -> Path:
    root = inbox_root(cfg)
    root.mkdir(parents=True, exist_ok=True)
    return root


# ------------------------------------------------------------------ import


def _write_mokuro(dest: Path, volume: Volume) -> None:
    pages = []
    for page in volume.pages:
        pages.append(
            {
                "img_path": page.image.name,
                "img_width": page.width,
                "img_height": page.height,
                "blocks": [
                    {"box": list(b.box), "vertical": b.vertical, "font_size": b.font_size, "lines": b.lines,
                     "lines_coords": b.lines_coords}
                    for b in (page.blocks or [])
                ],
                "ocr": page.blocks is not None,
            }
        )
    data = {"title": volume.series, "volume": volume.title, "volume_uuid": volume.uid, "pages": pages}
    (dest / "volume.mokuro").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _place(cfg: AppConfig, lang: str, volume: Volume, images_dir: Path, mokuro_file: Path | None) -> Path:
    """Move a volume into the library and normalise it to volume.mokuro + volume/."""
    dest = library_root(cfg) / lang / _safe(volume.series) / f"{_safe(volume.title, 40)}-{hashlib.sha1(volume.uid.encode()).hexdigest()[:6]}"
    dest.mkdir(parents=True, exist_ok=True)
    target_images = dest / "volume"
    if target_images.exists():
        shutil.rmtree(target_images)  # our own half-finished earlier attempt
    shutil.move(str(images_dir), str(target_images))
    moved = Volume(
        volume.series,
        volume.title,
        volume.uid,
        [type(p)(target_images / p.image.name, p.width, p.height, p.blocks) for p in volume.pages],
    )
    _write_mokuro(dest, moved)
    if mokuro_file and mokuro_file.exists():
        shutil.move(str(mokuro_file), str(dest / "original.mokuro"))
    return dest


def _existing(conn: Connection, uid: str) -> int | None:
    return conn.execute(text("SELECT id FROM content_items WHERE source = 'mokuro' AND external_id = :e"), {"e": uid}).scalar()


def _collection(conn: Connection, lang: str, series: str) -> int:
    found = conn.execute(
        text("SELECT id FROM collections WHERE language_code = :l AND kind = 'manga_series' AND title = :t"),
        {"l": lang, "t": series},
    ).scalar()
    if found:
        return found
    return conn.execute(
        text("INSERT INTO collections (language_code, kind, title) VALUES (:l, 'manga_series', :t)"), {"l": lang, "t": series}
    ).lastrowid


def register_volume(conn: Connection, cfg: AppConfig, lang: str, dest: Path) -> tuple[int, bool]:
    """Create the library item for a placed volume and fill it. Returns (item id, analysed now?)."""
    volume = read_mokuro(dest / "volume.mokuro")
    rel = dest.relative_to(cfg.data_dir).as_posix()
    item_id = conn.execute(
        text(
            "INSERT INTO content_items (language_code, type, title, creator, collection_id, collection_index, origin, source, "
            "external_id, local_path, cover_path, page_count, metadata_json) VALUES (:l, 'manga_volume', :title, NULL, :c, :ci, "
            "'user_added', 'mokuro', :uid, :path, :cover, :pages, :meta)"
        ),
        {
            "l": lang, "title": f"{volume.series} · {volume.title}" if volume.title != volume.series else volume.title,
            "c": _collection(conn, lang, volume.series), "ci": _volume_number(volume.title), "uid": volume.uid, "path": rel,
            "cover": f"{rel}/volume/{volume.pages[0].image.name}", "pages": len(volume.pages),
            "meta": json.dumps({"series": volume.series, "volume": volume.title}, ensure_ascii=False),
        },
    ).lastrowid
    return item_id, fill_volume(conn, cfg, item_id, lang, dest)


def fill_volume(conn: Connection, cfg: AppConfig, item_id: int, lang: str, dest: Path) -> bool:
    """(Re)write pages, text blocks and text chunks from dest/volume.mokuro, then analyse. Returns analysed now?"""
    conn.execute(text("DELETE FROM manga_pages WHERE content_item_id = :i"), {"i": item_id})
    conn.execute(text("DELETE FROM content_chunks WHERE content_item_id = :i"), {"i": item_id})
    volume = read_mokuro(dest / "volume.mokuro")
    raw_pages = json.loads((dest / "volume.mokuro").read_text(encoding="utf-8"))["pages"]
    rel = dest.relative_to(cfg.data_dir).as_posix()
    chunk_rows = []
    chars = 0
    for index, (page, raw) in enumerate(zip(volume.pages, raw_pages)):
        page_id = conn.execute(
            text(
                "INSERT INTO manga_pages (content_item_id, page_index, image_path, width, height, ocr_status) "
                "VALUES (:i, :n, :p, :w, :h, :s)"
            ),
            {
                "i": item_id, "n": index, "p": f"{rel}/volume/{page.image.name}", "w": page.width, "h": page.height,
                "s": "done" if raw.get("ocr", True) else "pending",
            },
        ).lastrowid
        for seq, block in enumerate(page.blocks or []):
            joined = block_text(block.lines, lang)
            conn.execute(
                text(
                    "INSERT INTO manga_text_blocks (page_id, seq, x1, y1, x2, y2, vertical, font_size, lines_json, text) "
                    "VALUES (:p, :s, :x1, :y1, :x2, :y2, :v, :f, :lines, :t)"
                ),
                {
                    "p": page_id, "s": seq, "x1": block.box[0], "y1": block.box[1], "x2": block.box[2], "y2": block.box[3],
                    "v": int(block.vertical), "f": block.font_size, "t": joined,
                    "lines": json.dumps(
                        [{"text": line, "coords": block.lines_coords[i] if i < len(block.lines_coords) else None}
                         for i, line in enumerate(block.lines)],
                        ensure_ascii=False,
                    ),
                },
            )
            chunk_rows.append({"id": item_id, "seq": len(chunk_rows), "loc": f"manga:p{index + 1}:b{seq}", "text": joined})
            chars += len(joined)
    conn.execute(text("UPDATE content_items SET page_count = :n WHERE id = :i"), {"n": len(volume.pages), "i": item_id})
    if not chunk_rows:
        conn.execute(text("UPDATE content_items SET analysis_status = 'no_text' WHERE id = :id"), {"id": item_id})
        return False
    conn.execute(text("INSERT INTO content_chunks (content_item_id, seq, locator, text) VALUES (:id, :seq, :loc, :text)"), chunk_rows)
    if chars <= INLINE_ANALYSIS_CHARS:
        analyze_item(conn, item_id)
        return True
    from app.jobs.runner import enqueue

    conn.execute(text("UPDATE content_items SET analysis_status = 'queued' WHERE id = :id"), {"id": item_id})
    enqueue(conn, "analyze_content", {"item_id": item_id}, dedupe=False)
    return False


def _language_for(cfg: AppConfig, root: Path, path: Path) -> str:
    """data/inbox/manga/de/… imports as German; anything else as Japanese."""
    first = path.relative_to(root).parts[0] if path != root else ""
    return first if first in cfg.language_codes else "ja"


def _import_found(conn: Connection, cfg: AppConfig, lang: str, path: Path) -> dict[str, Any]:
    if path.suffix == ".mokuro":
        volume = read_mokuro(path)
        images_dir, mokuro_file = path.with_suffix(""), path
    else:
        volume = read_image_folder(path)
        images_dir, mokuro_file = path, None
    existing = _existing(conn, volume.uid)
    if existing:
        return {"title": volume.title, "status": "already in library", "item_id": existing}
    dest = _place(cfg, lang, volume, images_dir, mokuro_file)
    if not mokuro_file:
        ocr_dir = path.parent / "_ocr" / path.name
        if ocr_dir.is_dir():
            shutil.move(str(ocr_dir), str(dest / "_ocr"))
    item_id, _ = register_volume(conn, cfg, lang, dest)
    return {
        "title": volume.title,
        "status": "imported" if volume.has_text else "imported (no OCR text yet)",
        "item_id": item_id,
        "pages": len(volume.pages),
    }


def _move_aside(root: Path, path: Path) -> None:
    target = root / "_imported" / path.relative_to(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target = target.with_name(f"{target.stem}-{hashlib.sha1(str(path).encode()).hexdigest()[:6]}{target.suffix}")
    shutil.move(str(path), str(target))


def scan_inbox(conn: Connection, cfg: AppConfig) -> dict[str, Any]:
    root = ensure_inbox(cfg)
    results: list[dict[str, Any]] = []
    for path in find_volumes(root):
        if not path.exists():  # moved along with an earlier volume
            continue
        lang = _language_for(cfg, root, path)
        try:
            if path.suffix.lower() in {".zip", ".cbz"}:
                results.extend(_import_archive(conn, cfg, lang, path))
                _move_aside(root, path)
            else:
                result = _import_found(conn, cfg, lang, path)
                results.append(result)
                if result["status"] == "already in library":
                    for leftover in (path, path.with_suffix("") if path.suffix == ".mokuro" else None):
                        if leftover is not None and leftover.exists():
                            _move_aside(root, leftover)
        except (MangaError, OSError, zipfile.BadZipFile) as exc:
            results.append({"title": path.name, "status": f"skipped: {exc}"})
    _tidy(root, set(cfg.language_codes))
    return {"folder": str(root), "results": results, "imported": sum(1 for r in results if r["status"].startswith("imported"))}


def _import_archive(conn: Connection, cfg: AppConfig, lang: str, archive: Path) -> list[dict[str, Any]]:
    staging = library_root(cfg) / "_staging"
    staging.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=staging) as tmp:
        tmp_path = Path(tmp)
        with zipfile.ZipFile(archive) as zf:
            for member in zf.infolist():
                target = (tmp_path / member.filename).resolve()
                if not target.is_relative_to(tmp_path.resolve()):
                    raise MangaError(f"{archive.name} contains an unsafe path")
            zf.extractall(tmp_path)
        found = find_volumes(tmp_path)
        if not found and any(p.is_file() for p in tmp_path.iterdir()):
            # a flat CBZ: images at the top level
            folder = tmp_path / archive.stem
            folder.mkdir()
            for p in list(tmp_path.iterdir()):
                if p.is_file():
                    shutil.move(str(p), str(folder / p.name))
            found = [folder]
        results = []
        for path in found:
            if path.exists() and path.suffix.lower() not in {".zip", ".cbz"}:
                results.append(_import_found(conn, cfg, lang, path))
        if not results:
            raise MangaError(f"no manga pages found in {archive.name}")
        return results


def _tidy(root: Path, keep: set[str]) -> None:
    """Remove folders left empty after their contents were imported (never files, never the language folders)."""
    for folder in sorted((p for p in root.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        if "_imported" in folder.parts or (folder.parent == root and folder.name in keep):
            continue
        try:
            folder.rmdir()  # only succeeds when empty
        except OSError:
            pass


# ------------------------------------------------------------------ reading


def pages(conn: Connection, item_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            "SELECT p.id, p.page_index, p.width, p.height, p.ocr_status, COUNT(b.id) FROM manga_pages p "
            "LEFT JOIN manga_text_blocks b ON b.page_id = p.id WHERE p.content_item_id = :i GROUP BY p.id ORDER BY p.page_index"
        ),
        {"i": item_id},
    ).all()
    return [{"id": r[0], "n": r[1] + 1, "width": r[2], "height": r[3], "ocr": r[4], "blocks": r[5]} for r in rows]


def page(conn: Connection, item_id: int, number: int) -> dict[str, Any]:
    item = get_item(conn, item_id)
    if item["type"] != "manga_volume":
        raise ContentError("not a manga volume")
    all_pages = pages(conn, item_id)
    if not all_pages:
        raise ContentError("this volume has no pages")
    number = max(1, min(number, len(all_pages)))
    current = all_pages[number - 1]
    rows = conn.execute(
        text(
            "SELECT id, seq, x1, y1, x2, y2, vertical, font_size, lines_json, text, user_corrected FROM manga_text_blocks "
            "WHERE page_id = :p ORDER BY seq"
        ),
        {"p": current["id"]},
    ).all()
    blocks = []
    for r in rows:
        lines = [line["text"] for line in json.loads(r[8])]
        starts, cursor = [], 0
        separator = 0 if item["language"] == "ja" else 1
        for line in lines:
            starts.append(cursor)
            cursor += len(line.strip()) + separator
        blocks.append(
            {
                "id": r[0], "seq": r[1], "box": [r[2], r[3], r[4], r[5]], "vertical": bool(r[6]), "font_size": r[7],
                "lines": [{"text": line.strip(), "start": s} for line, s in zip(lines, starts)], "text": r[9],
                "corrected": bool(r[10]),
            }
        )
    tokens, summary = annotate_segments(conn, item["language"], [b["text"] for b in blocks]) if blocks else ([], None)
    for block, own in zip(blocks, tokens):
        block["tokens"] = own
    conn.execute(
        text("UPDATE content_items SET position_ref = :pos, last_opened_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = :id"),
        {"pos": f"page:{number}", "id": item_id},
    )
    return {
        "item": item,
        "page": number,
        "pages": len(all_pages),
        "width": current["width"],
        "height": current["height"],
        "ocr": current["ocr"],
        "blocks": blocks,
        "summary": summary,
    }


def image_path(cfg: AppConfig, conn: Connection, item_id: int, number: int) -> Path:
    rel = conn.execute(
        text("SELECT image_path FROM manga_pages WHERE content_item_id = :i AND page_index = :n"), {"i": item_id, "n": number - 1}
    ).scalar()
    if not rel:
        raise ContentError("no such page")
    path = (cfg.data_dir / rel).resolve()
    if not path.is_relative_to(cfg.data_dir.resolve()) or not path.is_file():
        raise ContentError("page image is missing")
    return path


def volume_vocab(conn: Connection, item_id: int, limit: int = 80) -> dict[str, Any]:
    """Words in this volume you probably don't know yet, most frequent first, with the page they first appear on."""
    item = get_item(conn, item_id)
    chunks = conn.execute(
        text("SELECT locator, text FROM content_chunks WHERE content_item_id = :i ORDER BY seq"), {"i": item_id}
    ).all()
    if not chunks:
        return {"item_id": item_id, "words": [], "total_unknown": 0}
    tokens, _ = annotate_segments(conn, item["language"], [c[1] for c in chunks])
    stats: dict[tuple[str, str], dict[str, Any]] = {}
    pages_of: dict[tuple[str, str], set[int]] = defaultdict(set)
    for (locator, sentence), own in zip(chunks, tokens):
        page_no = int(locator.split(":")[1][1:])
        for token in own:
            if not token["learnable"] or token["status"] not in {"new", "learning", "familiar"}:
                continue
            key = (token["lemma"], token["reading"])
            entry = stats.setdefault(
                key,
                {"lemma": token["lemma"], "reading": token["reading"], "display": token["display"], "pos": token["pos"],
                 "status": token["status"], "rank": token["rank"], "count": 0, "first_page": page_no, "example": sentence},
            )
            entry["count"] += 1
            pages_of[key].add(page_no)
    words = sorted(stats.values(), key=lambda w: (-w["count"], w["rank"] or 10**6))
    for word in words:
        word["pages"] = len(pages_of[(word["lemma"], word["reading"])])
    return {"item_id": item_id, "words": words[:limit], "total_unknown": len(words)}


def correct_block(conn: Connection, block_id: int, lines: list[str]) -> dict[str, Any]:
    row = conn.execute(
        text(
            "SELECT b.page_id, b.seq, b.lines_json, p.content_item_id, p.page_index, ci.language_code FROM manga_text_blocks b "
            "JOIN manga_pages p ON p.id = b.page_id JOIN content_items ci ON ci.id = p.content_item_id WHERE b.id = :b"
        ),
        {"b": block_id},
    ).first()
    if not row:
        raise ContentError("no such text block")
    page_id, seq, old_json, item_id, page_index, lang = row
    old = json.loads(old_json)
    clean = [line.strip() for line in lines if line.strip()]
    if not clean:
        raise ContentError("a text block needs at least one line")
    new_lines = [{"text": line, "coords": old[i]["coords"] if i < len(old) else None} for i, line in enumerate(clean)]
    joined = block_text(clean, lang)
    conn.execute(
        text("UPDATE manga_text_blocks SET lines_json = :l, text = :t, user_corrected = 1 WHERE id = :b"),
        {"l": json.dumps(new_lines, ensure_ascii=False), "t": joined, "b": block_id},
    )
    conn.execute(
        text("UPDATE content_chunks SET text = :t WHERE content_item_id = :i AND locator = :loc"),
        {"t": joined, "i": item_id, "loc": f"manga:p{page_index + 1}:b{seq}"},
    )
    analyze_item(conn, item_id)
    return {"id": block_id, "text": joined}


# ------------------------------------------------------------------ optional OCR


def mokuro_available() -> bool:
    return shutil.which("mokuro") is not None


def run_ocr(conn: Connection, cfg: AppConfig, item_id: int) -> dict[str, Any]:
    """Run mokuro on a volume that has no text yet (needs `mokuro` installed; uses the GPU if present)."""
    item = get_item(conn, item_id)
    if not item["local_path"]:
        raise ContentError("this volume has no local folder")
    dest = cfg.data_dir / item["local_path"]
    exe = shutil.which("mokuro")
    if not exe:
        raise ContentError("mokuro is not installed")
    images = dest / "volume"
    subprocess.run([exe, str(images), "--disable_confirmation=true"], check=True, timeout=6 * 3600)
    fresh = read_mokuro(dest / "volume.mokuro")  # mokuro writes <folder>.mokuro next to the folder
    _write_mokuro(dest, fresh)
    fill_volume(conn, cfg, item_id, item["language"], dest)
    return {"item_id": item_id, "pages": len(fresh.pages), "has_text": fresh.has_text}
