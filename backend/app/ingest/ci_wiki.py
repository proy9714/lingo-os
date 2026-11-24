"""Comprehensible Input Wiki (comprehensibleinputwiki.org, content CC0): the resources listed for a language.

Only the public /wiki/<Language> pages are read, at most once a week, as robots.txt allows; the API is disallowed and
never used. Each resource is a paragraph: an external link, an optional note, and icons for its type and flags.
"""

from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

import httpx

from app.ingest.feeds import USER_AGENT

def _pages() -> dict[str, str]:
    from app.languages.registry import CATALOG

    return {spec.code: spec.wiki_page for spec in CATALOG if spec.wiki_page}


PAGES = _pages()
BASE = "https://comprehensibleinputwiki.org/wiki/"

ICONS = {
    "Video_camera_icon": "video",
    "Pod.png": "podcast",
    "Book_": "reading",
    "Caption_icon": "captions",
    "Icon-app": "app",
    "Money_icon": "paid",
    "AI_icon": "ai_generated",
    "Rainbow_circle": "all_levels",
}
LEVEL = re.compile(
    r"\b(super ?beginner|beginners?|intermediate|advanced|upper[- ]intermediate|all levels|"
    r"[ABC][12](?:\s*[-–]\s*[ABC][12])?|N[1-5](?:\s*[-–]\s*N[1-5])?)\b",
    re.I,
)


class WikiError(Exception):
    pass


@dataclass
class Resource:
    name: str
    url: str
    section: str
    note: str = ""
    flags: list[str] = field(default_factory=list)
    level_label: str | None = None
    youtube_url: str | None = None  # the resource's YouTube channel, when it links one

    @property
    def kind(self) -> str:
        if YOUTUBE_CHANNEL.search(self.url):
            return "youtube_channel"
        if "youtube.com/playlist" in self.url:
            return "youtube_playlist"
        return "web_section"


YOUTUBE_CHANNEL = re.compile(r"youtube\.com/(@|channel/|c/|user/)")
SKIP_SECTIONS = ("Contents", "Navigation", "Wiki tools", "Page tools", "Categories", "Content about")


class _Parser(HTMLParser):
    """Walks the article body. A resource is a paragraph or a top-level list item that starts with an external link;
    nested list items add notes, flags and extra links (often the YouTube channel of a website)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_body = False
        self.sections: dict[int, str] = {}
        self.in_heading = False
        self.heading_text = ""
        self.level = 2
        self.li_depth = 0
        self.container: str | None = None  # 'p' or 'li' while collecting a resource
        self.current: dict | None = None
        self.in_link = False
        self.resources: list[Resource] = []

    def _open(self, kind: str) -> None:
        self.container = kind
        self.current = {"name": "", "url": None, "rest": "", "flags": [], "links": []}

    def _close(self) -> None:
        cur, self.container, self.current = self.current, None, None
        if not cur or not cur["url"] or not cur["name"].strip():
            return
        section = " / ".join(self.sections[k] for k in sorted(self.sections))
        if any(part.startswith(SKIP_SECTIONS) for part in section.split(" / ")):
            return
        note = re.sub(r"\s+", " ", cur["rest"]).strip(" ()-–")
        level = LEVEL.search(f"{note} {section}")
        youtube = cur["url"] if YOUTUBE_CHANNEL.search(cur["url"]) else next(
            (link for link in cur["links"] if YOUTUBE_CHANNEL.search(link)), None
        )
        self.resources.append(
            Resource(
                name=html_lib.unescape(cur["name"].strip()),
                url=cur["url"],
                section=section,
                note=note[:400],
                flags=cur["flags"],
                level_label=level.group(0) if level else ("all levels" if "all_levels" in cur["flags"] else None),
                youtube_url=youtube,
            )
        )

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if not self.in_body:
            if a.get("id") == "mw-content-text":
                self.in_body = True
            return
        if tag in {"h2", "h3", "h4"}:
            if self.container:
                self._close()
            self.in_heading, self.heading_text, self.level = True, "", int(tag[1])
        elif tag == "p" and self.li_depth == 0:
            self._open("p")
        elif tag == "li":
            self.li_depth += 1
            if self.li_depth == 1:
                self._open("li")
        elif tag == "a" and self.current is not None:
            href = a.get("href") or ""
            if "external" in (a.get("class") or "") and href.startswith("http"):
                if self.current["url"] is None and not self.current["rest"].strip():
                    self.current["url"] = href
                    self.in_link = True
                else:
                    self.current["links"].append(href)
        elif tag == "img" and self.current is not None:
            src = a.get("src") or ""
            for key, flag in ICONS.items():
                if key in src and flag not in self.current["flags"]:
                    self.current["flags"].append(flag)

    def handle_endtag(self, tag: str) -> None:
        if not self.in_body:
            return
        if tag in {"h2", "h3", "h4"} and self.in_heading:
            self.in_heading = False
            self.sections[self.level] = self.heading_text.replace("[edit | edit source]", "").strip()
            for deeper in [k for k in self.sections if k > self.level]:
                del self.sections[deeper]
        elif tag == "a":
            self.in_link = False
        elif tag == "p" and self.container == "p":
            self._close()
        elif tag == "li":
            if self.li_depth == 1 and self.container == "li":
                self._close()
            self.li_depth = max(0, self.li_depth - 1)

    def handle_data(self, data: str) -> None:
        if not self.in_body:
            return
        if self.in_heading:
            self.heading_text += data
        elif self.current is not None:
            if self.in_link:
                self.current["name"] += data
            else:
                self.current["rest"] += " " + data


def parse_page(html: str) -> list[Resource]:
    parser = _Parser()
    parser.feed(html)
    seen: set[str] = set()
    out = []
    for r in parser.resources:
        if r.url in seen:
            continue
        seen.add(r.url)
        out.append(r)
    return out


def fetch_page(lang: str, timeout: float = 30) -> str:
    page = PAGES.get(lang)
    if not page:
        raise WikiError(f"the wiki has no page configured for '{lang}'")
    try:
        response = httpx.get(BASE + page, headers={"User-Agent": USER_AGENT}, timeout=timeout, follow_redirects=True)
    except httpx.HTTPError as exc:
        raise WikiError(f"couldn't reach the wiki: {exc}") from exc
    if response.status_code != 200:
        raise WikiError(f"the wiki answered {response.status_code}")
    return response.text
