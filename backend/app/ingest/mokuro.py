"""Manga volumes: mokuro OCR output (`.mokuro` + images, or the older `_ocr/` page JSONs) and plain image sets.

A `.mokuro` file is JSON: {title, volume, volume_uuid, pages: [{img_path, img_width, img_height, blocks: [...]}]},
where each block has a box [x1, y1, x2, y2], `vertical`, `font_size`, `lines` and `lines_coords`.
The images live in a folder named like the `.mokuro` file (`Vol 01.mokuro` + `Vol 01/`).
"""

from __future__ import annotations

import json
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}


class MangaError(Exception):
    pass


@dataclass
class Block:
    box: tuple[float, float, float, float]
    vertical: bool
    font_size: float | None
    lines: list[str]
    lines_coords: list[Any] = field(default_factory=list)


@dataclass
class Page:
    image: Path
    width: int
    height: int
    blocks: list[Block] | None  # None: no OCR for this page yet


@dataclass
class Volume:
    series: str
    title: str
    uid: str
    pages: list[Page]

    @property
    def has_text(self) -> bool:
        return any(p.blocks for p in self.pages)


def natural_key(name: str) -> list[Any]:
    """'page10' after 'page9'."""
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", name)]


def image_size(path: Path) -> tuple[int, int]:
    """Width and height from the file header (PNG, JPEG, WebP, GIF) without an imaging library."""
    with path.open("rb") as fh:
        head = fh.read(32)
        if head.startswith(b"\x89PNG"):
            return struct.unpack(">II", head[16:24])
        if head[:6] in (b"GIF87a", b"GIF89a"):
            return struct.unpack("<HH", head[6:10])
        if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
            chunk = head[12:16]
            if chunk == b"VP8X":
                w = int.from_bytes(head[24:27], "little") + 1
                fh.seek(27)
                h = int.from_bytes(fh.read(3), "little") + 1
                return w, h
            if chunk == b"VP8 ":
                fh.seek(26)
                w, h = struct.unpack("<HH", fh.read(4))
                return w & 0x3FFF, h & 0x3FFF
            if chunk == b"VP8L":
                bits = int.from_bytes(head[21:25], "little")
                return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        if head[:2] == b"\xff\xd8":
            fh.seek(2)
            while True:
                marker = fh.read(2)
                if len(marker) < 2 or marker[0] != 0xFF:
                    break
                if marker[1] in (0xD8, 0x01) or 0xD0 <= marker[1] <= 0xD7:
                    continue
                length = struct.unpack(">H", fh.read(2))[0]
                if marker[1] in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    _precision, h, w = struct.unpack(">BHH", fh.read(5))
                    return w, h
                fh.seek(length - 2, 1)
    raise MangaError(f"can't read the size of {path.name}")


def _blocks(raw: list[dict[str, Any]]) -> list[Block]:
    blocks = []
    for b in raw:
        lines = [str(line) for line in b.get("lines") or [] if str(line).strip()]
        box = b.get("box") or [0, 0, 0, 0]
        if not lines or len(box) != 4:
            continue
        blocks.append(
            Block(
                box=tuple(float(v) for v in box),  # type: ignore[arg-type]
                vertical=bool(b.get("vertical", True)),
                font_size=float(b["font_size"]) if b.get("font_size") else None,
                lines=lines,
                lines_coords=b.get("lines_coords") or [],
            )
        )
    return blocks


def images_in(folder: Path) -> list[Path]:
    return sorted((p for p in folder.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES), key=lambda p: natural_key(p.name))


def read_mokuro(path: Path) -> Volume:
    """A `.mokuro` file plus its image folder."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise MangaError(f"{path.name} is not a readable .mokuro file") from exc
    folder = path.with_suffix("")
    if not folder.is_dir():
        raise MangaError(f"the images for {path.name} should be in a folder named '{folder.name}'")
    pages = []
    for raw in data.get("pages") or []:
        image = folder / raw.get("img_path", "")
        if not image.is_file():
            continue
        width, height = raw.get("img_width"), raw.get("img_height")
        if not width or not height:
            width, height = image_size(image)
        pages.append(Page(image, int(width), int(height), _blocks(raw.get("blocks") or [])))
    if not pages:
        raise MangaError(f"no page images found for {path.name}")
    title = str(data.get("volume") or path.stem)
    series = str(data.get("title") or folder.parent.name or title)
    uid = str(data.get("volume_uuid") or f"{series}/{title}")
    return Volume(series=series, title=title, uid=uid, pages=pages)


def read_image_folder(folder: Path, series: str | None = None) -> Volume:
    """A folder of page images. Uses mokuro's older `_ocr/<volume>/<page>.json` files if they sit next to it."""
    images = images_in(folder)
    if not images:
        raise MangaError(f"no images in {folder.name}")
    ocr_dir = folder.parent / "_ocr" / folder.name
    pages = []
    for image in images:
        blocks = None
        page_json = ocr_dir / f"{image.stem}.json"
        if page_json.is_file():
            raw = json.loads(page_json.read_text(encoding="utf-8"))
            blocks = _blocks(raw.get("blocks") or [])
            width, height = raw.get("img_width"), raw.get("img_height")
        else:
            width = height = None
        if not width or not height:
            width, height = image_size(image)
        pages.append(Page(image, int(width), int(height), blocks))
    series_name = series or (folder.parent.name if folder.parent.name not in {"manga", "inbox"} else folder.name)
    return Volume(series=series_name, title=folder.name, uid=f"{series_name}/{folder.name}", pages=pages)


def find_volumes(root: Path) -> list[Path]:
    """Importable things under `root`: .mokuro files, and image folders that don't belong to one."""
    found: list[Path] = []
    if not root.is_dir():
        return found
    mokuro_dirs = set()
    for path in sorted(root.rglob("*.mokuro")):
        if "_imported" in path.parts:
            continue
        found.append(path)
        mokuro_dirs.add(path.with_suffix(""))
    for folder in sorted(p for p in root.rglob("*") if p.is_dir()):
        if "_imported" in folder.parts or "_ocr" in folder.parts or folder in mokuro_dirs:
            continue
        if any(parent in mokuro_dirs for parent in folder.parents):
            continue
        if images_in(folder):
            found.append(folder)
    for archive in sorted(root.rglob("*")):
        if archive.suffix.lower() in {".zip", ".cbz"} and "_imported" not in archive.parts:
            found.append(archive)
    return found


def block_text(lines: list[str], lang: str) -> str:
    """Lines of languages written without spaces (Japanese, Chinese) join directly; others with a space."""
    from app.languages.registry import get

    spec = get(lang)
    return ("" if spec and not spec.spaced else " ").join(line.strip() for line in lines)
