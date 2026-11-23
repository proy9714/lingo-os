"""Turn Yomitan glossary items (strings, structured content, deinflection arrays) into compact data.

Output stored in dict_terms.glossary_json:
    {"g": [glosses], "p": [parts of speech], "n": "grammar note", "f": [{"lemma": ..., "rules": [...]}]}
Raw structured content is large (Jitendex is ~545 MB unzipped); only what the app shows is kept.
"""

from __future__ import annotations

import re
from typing import Any

GLOSS_CONTAINERS = {"glossary", "glosses"}
SKIP_MARKERS = ("example", "attribution", "preamble", "details", "summary", "xref", "antonym", "backlink", "forms")
POS_MARKERS = {"part-of-speech-info"}
NOTE_MARKERS = {"Grammar-content"}
NOISE_TAGS = {"★", "priority", "form", "non-lemma"}
MAX_GLOSSES = 12
MAX_GLOSS_CHARS = 300
_SPACES = re.compile(r"\s+")


def _marker(node: dict[str, Any]) -> str:
    data = node.get("data")
    return str(data.get("content", "")) if isinstance(data, dict) else ""


def _text(node: Any, skip: bool = True) -> str:
    """All visible text under a node, skipping examples/attribution, dropping ruby readings."""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(_text(child, skip) for child in node)
    if not isinstance(node, dict):
        return ""
    if node.get("tag") in {"rt", "rp"}:
        return ""
    if skip and any(m in _marker(node) for m in SKIP_MARKERS):
        return ""
    text = _text(node.get("content"), skip)
    if node.get("tag") in {"div", "li", "p", "br"}:
        text = f" {text} "
    return text


def _clean(text: str) -> str:
    return _SPACES.sub(" ", text).strip()[:MAX_GLOSS_CHARS]


def _walk(node: Any, out: dict[str, list[str]]) -> None:
    if isinstance(node, list):
        for child in node:
            _walk(child, out)
        return
    if not isinstance(node, dict):
        return
    marker = _marker(node)
    if marker in POS_MARKERS:
        out["p"].append(_clean(_text(node, skip=False)))
        return
    if marker in NOTE_MARKERS:
        out["n"].append(_clean(_text(node, skip=False)))
        return
    if marker in GLOSS_CONTAINERS:
        content = node.get("content")
        items = content if isinstance(content, list) else [content]
        for item in items:
            gloss = _clean(_text(item))
            if gloss:
                out["g"].append(gloss)
        return
    if any(m in marker for m in SKIP_MARKERS) and marker not in NOTE_MARKERS:
        # still look inside <details> for the grammar note
        if "details" in marker or "preamble" in marker:
            _walk(node.get("content"), out)
        return
    _walk(node.get("content"), out)


def compact(definition_tags: str, glossary: list[Any]) -> dict[str, Any]:
    out: dict[str, list[str]] = {"g": [], "p": [], "n": []}
    forms: list[dict[str, Any]] = []
    for item in glossary:
        if isinstance(item, str):
            if item.strip():
                out["g"].append(_clean(item))
        elif isinstance(item, list) and len(item) == 2 and isinstance(item[0], str):
            forms.append({"lemma": item[0], "rules": [str(r) for r in (item[1] or [])][:4]})
        elif isinstance(item, dict):
            if item.get("type") == "text":
                out["g"].append(_clean(str(item.get("text", ""))))
            elif item.get("type") == "structured-content":
                before = len(out["g"])
                _walk(item.get("content"), out)
                if len(out["g"]) == before:  # no explicit gloss list: use the visible text
                    text = _clean(_text(item.get("content")))
                    if text:
                        out["g"].append(text)
    pos = [p for p in dict.fromkeys(out["p"] + definition_tags.split()) if p and p not in NOISE_TAGS]
    result: dict[str, Any] = {"g": list(dict.fromkeys(g for g in out["g"] if g))[:MAX_GLOSSES]}
    if pos:
        result["p"] = pos[:6]
    if out["n"]:
        result["n"] = out["n"][0]
    if forms:
        result["f"] = forms
    return result
