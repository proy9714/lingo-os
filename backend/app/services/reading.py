"""Books, PDFs, articles and saved texts: import into the library, split into pages, annotate a page."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, text

from app.config import AppConfig
from app.ingest.documents import Document
from app.services.annotate import annotate_segments
from app.services.content import ContentError, analyze_item, chunks_of, get_item, set_metadata

PAGE_CHARS = 2400
INLINE_ANALYSIS_CHARS = 60_000  # bigger documents are analysed by a background job


def books_root(cfg: AppConfig) -> Path:
    return cfg.data_dir / "library" / "books"


def store_upload(cfg: AppConfig, lang: str, filename: str, data: bytes) -> Path:
    folder = books_root(cfg) / lang
    folder.mkdir(parents=True, exist_ok=True)
    safe = "".join(c for c in Path(filename).name if c.isalnum() or c in "._- ")[:120] or "upload"
    target = folder / f"{hashlib.sha256(data).hexdigest()[:10]}_{safe}"
    target.write_bytes(data)
    return target


def import_document(
    conn: Connection,
    cfg: AppConfig,
    lang: str,
    doc: Document,
    *,
    item_type: str,
    source: str,
    source_url: str | None = None,
    local_path: Path | None = None,
) -> tuple[int, bool]:
    """Create the library item and its paragraphs. Returns (item id, analysed now?)."""
    external = source_url or (local_path.name if local_path else None)
    if external:
        existing = conn.execute(
            text("SELECT id FROM content_items WHERE source = :s AND external_id = :e"), {"s": source, "e": external}
        ).scalar()
        if existing:
            return existing, True
    rel = local_path.relative_to(cfg.data_dir).as_posix() if local_path else None
    item_id = conn.execute(
        text(
            "INSERT INTO content_items (language_code, type, title, creator, origin, source, source_url, external_id, "
            "local_path, page_count) VALUES (:l, :t, :title, :author, 'user_added', :s, :url, :ext, :path, :pages)"
        ),
        {
            "l": lang, "t": item_type, "title": doc.title[:300], "author": doc.author, "s": source, "url": source_url,
            "ext": external, "path": rel, "pages": len(doc.sections),
        },
    ).lastrowid
    rows = []
    seq = 0
    for s_index, section in enumerate(doc.sections):
        for p_index, paragraph in enumerate(section.paragraphs):
            locator = f"s{s_index}:p{p_index}" + (f"|{section.title[:80]}" if p_index == 0 and section.title else "")
            rows.append({"id": item_id, "seq": seq, "loc": locator, "text": paragraph})
            seq += 1
    conn.execute(text("INSERT INTO content_chunks (content_item_id, seq, locator, text) VALUES (:id, :seq, :loc, :text)"), rows)
    if doc.image or doc.site:
        set_metadata(conn, item_id, **{k: v for k, v in (("image", doc.image), ("site", doc.site)) if v})
    if doc.characters <= INLINE_ANALYSIS_CHARS:
        analyze_item(conn, item_id)
        return item_id, True
    conn.execute(text("UPDATE content_items SET analysis_status = 'queued' WHERE id = :id"), {"id": item_id})
    from app.jobs.runner import enqueue  # local import: jobs import services

    enqueue(conn, "analyze_content", {"item_id": item_id}, dedupe=False)
    return item_id, False


def pages(conn: Connection, item_id: int) -> list[dict[str, Any]]:
    """Page boundaries: a new page at each section start or every ~2,400 characters."""
    out: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    section = None
    for chunk in chunks_of(conn, item_id):
        locator = chunk["locator"]
        this_section = locator.split(":", 1)[0]
        title = locator.split("|", 1)[1] if "|" in locator else None
        new_section = this_section != section
        if current is None or new_section or current["chars"] + len(chunk["text"]) > PAGE_CHARS:
            current = {"n": len(out) + 1, "start": chunk["seq"], "end": chunk["seq"], "chars": 0, "title": title if new_section else None}
            out.append(current)
        current["end"] = chunk["seq"]
        current["chars"] += len(chunk["text"])
        section = this_section
    return out


def page(conn: Connection, item_id: int, number: int) -> dict[str, Any]:
    item = get_item(conn, item_id)
    all_pages = pages(conn, item_id)
    if not all_pages:
        raise ContentError("this item has no text")
    number = max(1, min(number, len(all_pages)))
    bounds = all_pages[number - 1]
    paragraphs = [c for c in chunks_of(conn, item_id) if bounds["start"] <= c["seq"] <= bounds["end"]]
    tokens, summary = annotate_segments(conn, item["language"], [p["text"] for p in paragraphs])
    for paragraph, own in zip(paragraphs, tokens):
        paragraph["tokens"] = own
    conn.execute(
        text("UPDATE content_items SET position_ref = :pos, last_opened_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = :id"),
        {"pos": f"page:{number}", "id": item_id},
    )
    return {
        "item": item,
        "page": number,
        "pages": len(all_pages),
        "title": bounds["title"],
        "paragraphs": paragraphs,
        "summary": summary,
    }


def record_page_progress(conn: Connection, item_id: int, number: int, total: int) -> None:
    progress = min(1.0, number / total) if total else 0
    conn.execute(
        text(
            "UPDATE content_items SET progress = MAX(progress, :p), position_ref = :pos, status = CASE WHEN :p >= 0.98 THEN "
            "'finished' WHEN status IN ('library', 'candidate') THEN 'in_progress' ELSE status END WHERE id = :id"
        ),
        {"p": progress, "pos": f"page:{number}", "id": item_id},
    )


