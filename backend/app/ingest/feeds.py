"""RSS and Atom feeds (stdlib XML; feeds are small)."""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import httpx

USER_AGENT = "LingoOS/0.1 (personal language-learning app)"


RUBY_READINGS = re.compile(r"<r[tp](?=[\s>])[^>]*>.*?</r[tp]>", re.IGNORECASE | re.DOTALL)
TAGS = re.compile(r"<[^>]+>")


def clean_title(raw: str) -> str:
    """Feed titles may carry escaped HTML, such as furigana: JR<ruby>渋谷駅<rt>しぶやえき</rt></ruby> -> JR渋谷駅."""
    value = html.unescape(raw)
    value = TAGS.sub("", RUBY_READINGS.sub("", value))
    return " ".join(html.unescape(value).split())


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
                title = clean_title(child.text or "")
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


# ------------------------------------------------------------------ podcasts


@dataclass
class Episode:
    guid: str
    title: str
    published: str | None
    audio_url: str
    audio_type: str
    audio_bytes: int | None
    duration_sec: int | None
    image: str | None
    number: float | None
    description: str
    link: str | None
    transcripts: list[tuple[str, str]]  # (url, type) from <podcast:transcript>


@dataclass
class Podcast:
    title: str
    author: str | None
    image: str | None
    language: str | None
    description: str
    link: str | None
    episodes: list[Episode]


def parse_duration(value: str | None) -> int | None:
    """itunes:duration: "3725", "62:05" or "1:02:05"."""
    if not value:
        return None
    parts = value.strip().split(":")
    try:
        numbers = [float(p) for p in parts]
    except ValueError:
        return None
    seconds = 0.0
    for n in numbers:
        seconds = seconds * 60 + n
    return int(seconds) or None


def _text(node: ET.Element | None) -> str:
    return " ".join((node.text or "").split()) if node is not None else ""


def _child(node: ET.Element, name: str) -> ET.Element | None:
    return next((c for c in node if _local(c.tag) == name), None)


def _image(node: ET.Element) -> str | None:
    for child in node:
        name = _local(child.tag)
        if name == "image":
            href = child.get("href")  # itunes:image
            if href:
                return href
            url = _child(child, "url")  # RSS <image><url>
            if url is not None and _text(url):
                return _text(url)
    return None


def parse_podcast(xml: str) -> Podcast:
    """A podcast's RSS feed: the show and its episodes (only those with an audio file)."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise FeedError(f"not a readable feed: {exc}") from exc
    channel = next((n for n in root.iter() if _local(n.tag) == "channel"), None)
    if channel is None:
        raise FeedError("this isn't a podcast feed (no <channel>)")
    show_image = _image(channel)
    episodes: list[Episode] = []
    for item in channel:
        if _local(item.tag) != "item":
            continue
        enclosure = _child(item, "enclosure")
        url = enclosure.get("url") if enclosure is not None else None
        if not url or not url.startswith("http"):
            continue
        guid = _text(_child(item, "guid")) or url
        title = clean_title(_child(item, "title").text or "") if _child(item, "title") is not None else ""
        try:
            size = int(enclosure.get("length") or 0) or None
        except ValueError:
            size = None
        number = _text(_child(item, "episode"))
        transcripts = [
            (c.get("url") or "", (c.get("type") or "").lower())
            for c in item
            if _local(c.tag) == "transcript" and (c.get("url") or "").startswith("http")
        ]
        description = _text(_child(item, "summary")) or _text(_child(item, "description"))
        episodes.append(
            Episode(
                guid=guid[:500],
                title=title or "Episode",
                published=_text(_child(item, "pubDate")) or None,
                audio_url=url,
                audio_type=(enclosure.get("type") or "audio/mpeg").lower(),
                audio_bytes=size,
                duration_sec=parse_duration(_text(_child(item, "duration"))),
                image=_image(item) or show_image,
                number=float(number) if number.replace(".", "", 1).isdigit() else None,
                description=clean_title(description)[:2000],
                link=_text(_child(item, "link")) or None,
                transcripts=transcripts,
            )
        )
    return Podcast(
        title=clean_title(_text(_child(channel, "title"))) or "Podcast",
        author=_text(_child(channel, "author")) or None,
        image=show_image,
        language=(_text(_child(channel, "language")) or None),
        description=clean_title(_text(_child(channel, "summary")) or _text(_child(channel, "description")))[:2000],
        link=_text(_child(channel, "link")) or None,
        episodes=episodes,
    )


def fetch_text(url: str, timeout: float = 20) -> str:
    try:
        response = httpx.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout, follow_redirects=True)
    except httpx.HTTPError as exc:
        raise FeedError(f"couldn't fetch {url}: {exc}") from exc
    if response.status_code != 200:
        raise FeedError(f"{url} answered {response.status_code}")
    return response.text
