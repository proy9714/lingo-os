"""Offline packs: everything a device needs to use an item with no laptop or server in reach.

A pack holds the item's text already split into words with your current statuses, plus the dictionary entries for
those words (a small subset of the full dictionaries), so reading and lookups work offline.

  text    books, articles and texts: their pages
  manga   the pages and text boxes; the device fetches the page images once while still in reach
  media   videos, audio and podcast episodes with a transcript: the interactive transcript (version 2). The recording
          itself is downloaded separately when there is one to download (`media`: a local file or a podcast episode);
          YouTube videos can't be saved, so for them the pack is a read-along transcript.

Packs work for any device: the phone (registered in offline_packs, so Settings can list them) and the browser on a
computer.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import Connection, text

from app.dictionary.lookup import lookup as dict_lookup
from app.services import manga, reading
from app.services.annotate import annotate_segments
from app.services.content import READ_TYPES, WATCH_TYPES, ContentError, annotated_transcript, chunks_of, get_item

PACK_VERSION = 2  # 2 adds "media" packs; text and manga packs are unchanged, so older apps still read them
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


def build_pack(conn: Connection, dict_conn: Connection, item_id: int, media: dict[str, Any] | None = None) -> dict[str, Any]:
    """The pack for an item. `media` describes the downloadable recording, if any (api/offline_media.media_info)."""
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
                {"seq": seq, "locator": by_seq[seq][0]["locator"], "text": by_seq[seq][0]["text"], "tokens": by_seq[seq][1]}
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
    elif item["type"] in WATCH_TYPES:
        transcript = annotated_transcript(conn, item_id)
        if not transcript["cues"]:
            raise PackError("this has no transcript yet: get captions or a transcript first, then save it")
        for cue in transcript["cues"]:
            all_tokens += cue.get("tokens", [])
        body = {"kind": "media", "pages": [], "transcript": transcript, "media": media or {"available": False, "via": "none"}}
    else:
        raise PackError("this kind of item can't be saved for offline use")
    keys = ("id", "language", "type", "title", "creator", "coverage", "page_count", "word_count", "duration_sec", "source", "external_id")
    return {
        "version": PACK_VERSION,
        "item": {k: item.get(k) for k in keys} | {"image": (item.get("metadata") or {}).get("image")},
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
