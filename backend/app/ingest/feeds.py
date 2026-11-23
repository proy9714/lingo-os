"""RSS and Atom feeds (stdlib XML; feeds are small)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass

import httpx

USER_AGENT = "LingoOS/0.1 (personal language-learning app)"


class FeedError(Exception):
    pass


@dataclass
class FeedEntry:
    title: str
    url: str
    published: str | None


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_feed(xml: str) -> list[FeedEntry]:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise FeedError(f"not a readable feed: {exc}") from exc
    entries: list[FeedEntry] = []
    for node in root.iter():
        name = _local(node.tag)
        if name not in {"item", "entry"}:
            continue
        title = url = published = None
        for child in node:
            child_name = _local(child.tag)
            if child_name == "title":
                title = (child.text or "").strip()
            elif child_name == "link":
                href = child.get("href")
                if href and child.get("rel", "alternate") == "alternate":
                    url = href
                elif child.text and child.text.strip():
                    url = child.text.strip()
            elif child_name in {"pubDate", "published", "updated", "date"} and not published:
                published = (child.text or "").strip() or None
        if title and url and url.startswith("http"):
            entries.append(FeedEntry(title, url, published))
    return entries


def fetch_feed(url: str, timeout: float = 20) -> list[FeedEntry]:
    try:
        response = httpx.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout, follow_redirects=True)
    except httpx.HTTPError as exc:
        raise FeedError(f"couldn't fetch the feed: {exc}") from exc
    if response.status_code != 200:
        raise FeedError(f"the feed answered {response.status_code}")
    return parse_feed(response.text)
