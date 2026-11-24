"""Search YouTube (Watch) or the news (Read) for anything, and rate every result for your level.

A search returns at once with what's known (results you've met before keep their level); then each new result is
measured in the background, a few at a time: a video's captions in your language are fetched and analysed, an
article is read and analysed. The page polls the search and fills in each level as it arrives.

Videos come from YouTube's own search (yt-dlp, no key). Articles come from Bing News' RSS search in your language
and region (no key), whose links point straight at the articles.
"""

from __future__ import annotations

import html
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.parse import parse_qs, quote_plus, urlparse

import httpx
from sqlalchemy import Engine, text
from sqlalchemy.exc import OperationalError

from app.config import AppConfig
from app.ingest import documents, youtube
from app.ingest.feeds import USER_AGENT
from app.languages import registry
from app.services import catalog, content, reading

ALL_BANDS = ["too_easy", "comfortable", "i_plus_1", "stretch", "too_hard"]
VIDEO_RESULTS = 18
ARTICLE_RESULTS = 16
KEEP_SECONDS = 30 * 60

_SEARCHES: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()
_POOL = ThreadPoolExecutor(max_workers=3, thread_name_prefix="search")


class SearchError(RuntimeError):
    pass


# ------------------------------------------------------------------ starting a search


def start(engine: Engine, cfg: AppConfig, lang: str, kind: str, query: str) -> dict[str, Any]:
    query = " ".join(query.split())[:200]
    if not query:
        raise SearchError("Type something to search for.")
    _forget_old()
    search_id = uuid.uuid4().hex[:12]
    if kind == "video":
        results = _video_results(engine, lang, query)
    else:
        results = _article_results(engine, lang, query)
    state = {"id": search_id, "language": lang, "kind": kind, "query": query, "results": results, "at": time.time()}
    with _LOCK:
        _SEARCHES[search_id] = state
    for result in results:
        if result["state"] == "measuring":
            _POOL.submit(_measure, engine, cfg, lang, kind, result)
    return snapshot(engine, search_id)


def _forget_old() -> None:
    with _LOCK:
        for key in [k for k, v in _SEARCHES.items() if time.time() - v["at"] > KEEP_SECONDS]:
            del _SEARCHES[key]


def _video_results(engine: Engine, lang: str, query: str) -> list[dict[str, Any]]:
    try:
        listings = youtube.search(query, VIDEO_RESULTS)
    except youtube.YouTubeError as exc:
        raise SearchError(f"YouTube search failed: {exc}") from exc
    results = []
    with engine.begin() as conn:
        for video in listings:
            existing = conn.execute(
                text("SELECT id, analysis_status FROM content_items WHERE source = 'youtube' AND external_id = :v AND language_code = :l"),
                {"v": video.video_id, "l": lang},
            ).first()
            if existing:
                item_id, analysed = existing[0], existing[1] == "done"
            else:
                item_id = content.upsert_youtube(
                    conn, lang, video.video_id, title=video.title, channel=video.channel, duration=video.duration,
                    origin="scraper", status="candidate",
                )
                content.set_metadata(conn, item_id, discovered_via=f"search: {query}", channel_url=video.channel_url)
                analysed = False
            no_captions = (content.get_item(conn, item_id)["metadata"] or {}).get("captions") == "none"
            state = "ready" if analysed else "no_captions" if no_captions else "measuring"
            results.append({"item_id": item_id, "video_id": video.video_id, "title": video.title, "state": state, "error": None})
    return results


def _bing_market(lang: str, variant: str | None) -> tuple[str, str]:
    spec = registry.spec(lang)
    locale = spec.variant(variant).locale  # e.g. pt-BR, fr-CA, zh-TW
    return locale.split("-")[0], locale


def _article_results(engine: Engine, lang: str, query: str) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        variant = conn.execute(text("SELECT variant FROM languages WHERE code = :c"), {"c": lang}).scalar()
    setlang, market = _bing_market(lang, variant)
    url = (
        f"https://www.bing.com/news/search?q={quote_plus(query)}&format=rss&setlang={setlang}"
        f"&mkt={market}&cc={market.split('-')[-1]}"
    )
    try:
        response = httpx.get(url, headers={"User-Agent": USER_AGENT}, timeout=20, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise SearchError(f"The news search failed: {exc}") from exc
    results = []
    seen = set()
    with engine.connect() as conn:
        for item in re.findall(r"<item>(.*?)</item>", response.text, re.S)[: ARTICLE_RESULTS * 2]:
            link = _article_url(re.search(r"<link>(.*?)</link>", item, re.S))
            if not link or link in seen:
                continue
            seen.add(link)
            title = html.unescape(re.sub(r"<[^>]+>", "", (re.search(r"<title>(.*?)</title>", item, re.S) or [None, ""])[1])).strip()
            source = re.search(r"<News:Source>(.*?)</News:Source>", item, re.S)
            image = re.search(r"<News:Image>(.*?)</News:Image>", item, re.S)
            existing = conn.execute(
                text("SELECT id, analysis_status FROM content_items WHERE source_url = :u AND language_code = :l"), {"u": link, "l": lang}
            ).first()
            results.append(
                {
                    "item_id": existing[0] if existing else None, "url": link, "title": title or link,
                    "site": html.unescape(source.group(1)).strip() if source else urlparse(link).netloc,
                    "image": html.unescape(image.group(1)).strip() if image else None,
                    "state": "ready" if existing and existing[1] == "done" else "measuring", "error": None,
                }
            )
            if len(results) >= ARTICLE_RESULTS:
                break
    return results


def _article_url(match: re.Match[str] | None) -> str | None:
    """Bing wraps each link in its click tracker: the real address is its `url` parameter."""
    if not match:
        return None
    raw = html.unescape(match.group(1).strip())
    inner = parse_qs(urlparse(raw).query).get("url")
    url = inner[0] if inner else raw
    return url if url.startswith(("http://", "https://")) else None


# ------------------------------------------------------------------ measuring in the background


_WRITE = threading.Lock()  # search workers write one at a time: analysing a text holds SQLite's write lock for seconds


def _write(engine: Engine, work):  # noqa: ANN001, ANN202
    """Run `work(conn)` in a transaction; if another job (the daily refresh, an import) holds the database, wait and retry."""
    for attempt in range(4):
        try:
            with _WRITE, engine.begin() as conn:
                return work(conn)
        except OperationalError as exc:
            if "locked" not in str(exc) or attempt == 3:
                raise
            time.sleep(2 + 3 * attempt)
    return None


def _measure(engine: Engine, cfg: AppConfig, lang: str, kind: str, result: dict[str, Any]) -> None:
    try:
        if kind == "video":
            try:
                captions = youtube.fetch_captions(result["video_id"], lang)
            except youtube.YouTubeError as exc:
                result.update(state="failed", error=str(exc)[:160])
                return
            outcome = _write(engine, lambda conn: catalog.measure(conn, result["item_id"], lang, captions, ALL_BANDS))
            result["state"] = "no_captions" if outcome == "no_captions" else "ready"
        else:
            try:
                doc = documents.fetch_article(result["url"])
            except documents.DocumentError as exc:
                result.update(state="failed", error=str(exc)[:160])
                return

            def save(conn):  # noqa: ANN001, ANN202
                item_id, _ = reading.import_document(
                    conn, cfg, lang, doc, item_type="article", source="web", source_url=result["url"]
                )
                conn.execute(
                    text("UPDATE content_items SET origin = 'scraper', status = CASE WHEN status = 'library' THEN 'candidate' ELSE status END WHERE id = :i"),
                    {"i": item_id},
                )
                content.set_metadata(conn, item_id, discovered_via=f"search: {result['title'][:80]}", site=result.get("site"))
                return item_id

            result.update(item_id=_write(engine, save), state="ready")
    except Exception as exc:  # noqa: BLE001 - one bad result never breaks the others
        result.update(state="failed", error=f"{type(exc).__name__}: {exc}"[:160])


# ------------------------------------------------------------------ reading a search back


def snapshot(engine: Engine, search_id: str) -> dict[str, Any]:
    with _LOCK:
        state = _SEARCHES.get(search_id)
    if not state:
        raise KeyError(search_id)
    out = []
    with engine.connect() as conn:
        for result in state["results"]:
            entry = {"state": result["state"], "error": result["error"], "title": result["title"], "item": None,
                     "url": result.get("url"), "site": result.get("site"), "image": result.get("image")}
            if result.get("item_id"):
                item = content.get_item(conn, result["item_id"])
                if result["state"] == "ready" and item["analysis_status"] in ("queued", "running", "pending") and item["coverage"] is None:
                    entry["state"] = "measuring"  # imported, still being analysed
                meta = item["metadata"] or {}
                entry["item"] = {
                    "id": item["id"], "type": item["type"], "kind": "video" if kind_is_video(item["type"]) else "reading",
                    "title": item["title"], "creator": item["creator"], "source": item["source"], "external_id": item["external_id"],
                    "duration_sec": item["duration_sec"], "word_count": item["word_count"], "coverage": item["coverage"],
                    "band": item["band"], "estimated": bool(item["estimated"]), "expected_unknown": item["expected_unknown"],
                    "image": meta.get("image") or result.get("image"), "site": meta.get("site") or result.get("site"), "watched": item["times_watched"] > 0
                    or item["status"] == "finished", "speech_wpm": item["speech_wpm"],
                }
            out.append(entry)
    pending = sum(1 for e in out if e["state"] == "measuring")
    return {"id": state["id"], "language": state["language"], "kind": state["kind"], "query": state["query"],
            "results": out, "pending": pending}


def kind_is_video(item_type: str) -> bool:
    return item_type in content.WATCH_TYPES
