"""Text out of books and web pages: EPUB (zip + OPF spine), PDF (pypdf) and articles (trafilatura).

Everything becomes sections of paragraphs; the reader shows them on a plain page with clickable words.
Japanese ruby readings (<rt>) are dropped from the text.
"""

from __future__ import annotations

import posixpath
import re
import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree

BLOCK_TAGS = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "br", "tr", "section", "article", "dd", "dt"}
SKIP_TAGS = {"rt", "rp", "script", "style", "head", "title", "nav"}
MAX_PARAGRAPH = 1200


class DocumentError(ValueError):
    pass


@dataclass
class Section:
    title: str | None
    paragraphs: list[str] = field(default_factory=list)


@dataclass
class Document:
    title: str
    author: str | None
    language: str | None
    sections: list[Section]

    @property
    def characters(self) -> int:
        return sum(len(p) for s in self.sections for p in s.paragraphs)


class _TextCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.paragraphs: list[str] = []
        self.heading: str | None = None
        self._buffer: list[str] = []
        self._skip = 0
        self._in_heading = False

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        if tag in SKIP_TAGS:
            self._skip += 1
        elif tag in BLOCK_TAGS:
            self._flush()
            self._in_heading = tag in {"h1", "h2", "h3"}

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
        elif tag in BLOCK_TAGS:
            self._flush()

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._buffer.append(data)

    def _flush(self) -> None:
        text = re.sub(r"\s+", " ", "".join(self._buffer)).strip()
        self._buffer = []
        if text:
            if self._in_heading and self.heading is None:
                self.heading = text
            self.paragraphs.extend(_split_long(text))
        self._in_heading = False

    def close(self) -> None:
        super().close()
        self._flush()


def _split_long(text: str) -> list[str]:
    if len(text) <= MAX_PARAGRAPH:
        return [text]
    parts, current = [], ""
    for sentence in re.split(r"(?<=[.!?。！？])\s*", text):
        if current and len(current) + len(sentence) > MAX_PARAGRAPH:
            parts.append(current.strip())
            current = ""
        current += sentence + ("" if re.search(r"[。！？]$", sentence) else " ")
    if current.strip():
        parts.append(current.strip())
    return parts


def html_to_section(markup: str) -> Section:
    collector = _TextCollector()
    collector.feed(markup)
    collector.close()
    return Section(collector.heading, collector.paragraphs)


def parse_epub(path: Path) -> Document:
    ns = {"c": "urn:oasis:names:tc:opendocument:xmlns:container", "opf": "http://www.idpf.org/2007/opf", "dc": "http://purl.org/dc/elements/1.1/"}
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise DocumentError("not a valid EPUB file") from exc
    with archive:
        try:
            container = ElementTree.fromstring(archive.read("META-INF/container.xml"))
            opf_path = container.find(".//c:rootfile", ns).attrib["full-path"]  # type: ignore[union-attr]
            opf = ElementTree.fromstring(archive.read(opf_path))
        except (KeyError, AttributeError, ElementTree.ParseError) as exc:
            raise DocumentError("EPUB has no readable package file") from exc
        base = posixpath.dirname(opf_path)
        title = (opf.findtext(".//dc:title", default="", namespaces=ns) or path.stem).strip()
        author = (opf.findtext(".//dc:creator", default="", namespaces=ns) or "").strip() or None
        language = (opf.findtext(".//dc:language", default="", namespaces=ns) or "").strip()[:2] or None
        manifest = {
            item.attrib["id"]: item.attrib.get("href", "")
            for item in opf.findall(".//opf:manifest/opf:item", ns)
            if "nav" not in item.attrib.get("properties", "")
        }
        sections = []
        for ref in opf.findall(".//opf:spine/opf:itemref", ns):
            href = manifest.get(ref.attrib.get("idref", ""))
            if not href:
                continue
            name = posixpath.normpath(posixpath.join(base, href.split("#")[0]))
            try:
                markup = archive.read(name).decode("utf-8", errors="replace")
            except KeyError:
                continue
            section = html_to_section(markup)
            if section.paragraphs:
                sections.append(section)
    if not sections:
        raise DocumentError("no readable text found in this EPUB")
    return Document(title, author, language, sections)


def parse_pdf(path: Path) -> Document:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(str(path))
    except (PdfReadError, OSError, ValueError) as exc:
        raise DocumentError(f"could not open this PDF: {exc}") from exc
    meta = reader.metadata or {}
    sections = []
    for number, page in enumerate(reader.pages, start=1):
        raw = page.extract_text() or ""
        raw = re.sub(r"(\w)-\n(\w)", r"\1\2", raw)  # re-join words hyphenated across lines
        blocks = [re.sub(r"\s*\n\s*", " ", b).strip() for b in re.split(r"\n\s*\n", raw)]
        paragraphs = [p for b in blocks if b for p in _split_long(b)]
        if paragraphs:
            sections.append(Section(f"Page {number}", paragraphs))
    if not sections:
        raise DocumentError("this PDF has no text layer (a scanned PDF needs OCR, which isn't available yet)")
    return Document((meta.get("/Title") or path.stem).strip(), (meta.get("/Author") or "").strip() or None, None, sections)


def fetch_article(url: str) -> Document:
    import trafilatura

    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        raise DocumentError("could not download that page")
    result = trafilatura.bare_extraction(downloaded, url=url, include_comments=False, include_tables=False, with_metadata=True)
    if not result:
        raise DocumentError("no article text found on that page")
    data = result if isinstance(result, dict) else result.as_dict()
    text = (data.get("text") or "").strip()
    if len(text) < 200:
        raise DocumentError("no article text found on that page")
    paragraphs = [p for line in text.split("\n") if line.strip() for p in _split_long(line.strip())]
    return Document((data.get("title") or url).strip(), data.get("author"), data.get("language"), [Section(None, paragraphs)])


def parse_text(title: str, text: str) -> Document:
    paragraphs = [p for block in re.split(r"\n\s*\n|\n", text) if block.strip() for p in _split_long(block.strip())]
    if not paragraphs:
        raise DocumentError("the text is empty")
    return Document(title, None, None, [Section(None, paragraphs)])
