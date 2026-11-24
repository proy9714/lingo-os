"""Offline packs: everything the phone needs to read an item with no laptop around.

A pack holds the item's pages, already split into words with your current statuses, plus the dictionary entries for
those words (a small subset of the full dictionaries). Manga packs list the pages and text boxes; the phone fetches
the page images once while it is still on the home Wi-Fi.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import Connection, text

from app.dictionary.lookup import lookup as dict_lookup
from app.services import manga, reading
from app.services.annotate import annotate_segments
from app.services.content import READ_TYPES, ContentError, chunks_of, get_item

PACK_VERSION = 1
MAX_DICT_WORDS = 6000


class PackError(Exception):
    pass


def _dictionary(dict_conn: Connection, lang: str, tokens: list[dict[str, Any]]) -> dict[str, Any]:
    wanted: dict[str, dict[str, Any]] = {}
    for token in tokens:
        if token.get("learnable"):
            key = f"{token['lemma']}|{token['reading']}"
            entry = wanted.setdefault(key, {"lemma": token["lemma"], "reading": token["reading"], "forms": set()})
            entry["forms"].update(token.get("forms") or [])
    out: dict[str, Any] = {}
    for key, word in list(wanted.items())[:MAX_DICT_WORDS]:
        result = dict_lookup(dict_conn, lang, list(dict.fromkeys([word["lemma"], *sorted(word["forms"])])), word["reading"], limit=2)
        entries = [
            {"term": e["term"], "reading": e["reading"], "pos": e["pos"][:2], "glosses": e["glosses"][:4]} for e in result["entries"][:2]
        ]
        if entries:
            out[key] = entries
    return out


def build_pack(conn: Connection, dict_conn: Connection, item_id: int) -> dict[str, Any]:
    try:
        item = get_item(conn, item_id)
    except ContentError as exc:
        raise PackError(str(exc)) from exc
    lang = item["language"]
    all_tokens: list[dict[str, Any]] = []
    if item["type"] in READ_TYPES:
        chunks = chunks_of(conn, item_id)
        if not chunks:
            raise PackError("this item has no text")
        tokens, _ = annotate_segments(conn, lang, [c["text"] for c in chunks])
        by_seq = {c["seq"]: (c, own) for c, own in zip(chunks, tokens)}
        pages = []
        for bounds in reading.pages(conn, item_id):
            paragraphs = [
                {"seq": seq, "text": by_seq[seq][0]["text"], "tokens": by_seq[seq][1]}
                for seq in range(bounds["start"], bounds["end"] + 1)
                if seq in by_seq
            ]
            pages.append({"n": bounds["n"], "title": bounds["title"], "paragraphs": paragraphs})
            for p in paragraphs:
                all_tokens += p["tokens"]
        body: dict[str, Any] = {"kind": "text", "pages": pages}
    elif item["type"] == "manga_volume":
        pages = []
        for entry in manga.pages(conn, item_id):
            page = manga.page(conn, item_id, entry["n"], touch=False)
            pages.append({k: page[k] for k in ("page", "width", "height", "ocr", "blocks")})
            for block in page["blocks"]:
                all_tokens += block.get("tokens", [])
        body = {"kind": "manga", "pages": pages, "images": [f"/api/manga/{item_id}/image/{p['page']}" for p in pages]}
    else:
        raise PackError("videos stream from YouTube or the laptop and can't be packed; books, articles, texts and manga can")
    return {
        "version": PACK_VERSION,
        "item": {k: item[k] for k in ("id", "language", "type", "title", "creator", "coverage", "page_count", "word_count")},
        **body,
        "dictionary": _dictionary(dict_conn, lang, all_tokens),
    }


def register(conn: Connection, device_id: str, item_id: int, size: int) -> None:
    conn.execute(
        text(
            "INSERT INTO offline_packs (device_id, content_item_id, status, bytes, built_at) VALUES (:d, :i, 'ready', :b, "
            "strftime('%Y-%m-%dT%H:%M:%fZ','now')) ON CONFLICT(device_id, content_item_id) DO UPDATE SET status = 'ready', "
            "bytes = excluded.bytes, built_at = excluded.built_at"
        ),
        {"d": device_id, "i": item_id, "b": size},
    )


def pack_size(pack: dict[str, Any]) -> int:
    return len(json.dumps(pack, ensure_ascii=False).encode())


def device_packs(conn: Connection, device_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            "SELECT p.content_item_id, ci.title, ci.type, ci.language_code, p.status, p.bytes, p.built_at FROM offline_packs p "
            "JOIN content_items ci ON ci.id = p.content_item_id WHERE p.device_id = :d AND p.status != 'removed' ORDER BY p.built_at DESC"
        ),
        {"d": device_id},
    ).all()
    keys = ("item_id", "title", "type", "language", "status", "bytes", "built_at")
    return [dict(zip(keys, r)) for r in rows]
