"""A tiny Yomitan dictionary zip in the shapes the real dictionaries use (Wiktionary-style and Jitendex-style)."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path


def _wty(glosses: list[str], note: str) -> list:
    return [
        {
            "type": "structured-content",
            "content": [
                {
                    "tag": "div",
                    "content": [
                        {
                            "tag": "div",
                            "data": {"content": "preamble"},
                            "content": [
                                {
                                    "tag": "details",
                                    "data": {"content": "details-entry-Grammar"},
                                    "content": [
                                        {"tag": "summary", "data": {"content": "summary-entry"}, "content": "Grammar"},
                                        {"tag": "div", "data": {"content": "Grammar-content"}, "content": note},
                                    ],
                                }
                            ],
                        }
                    ],
                },
                {
                    "tag": "ol",
                    "data": {"content": "glosses"},
                    "content": [{"tag": "li", "content": [{"tag": "div", "content": [g]}]} for g in glosses],
                },
            ],
        }
    ]


GERMAN_ROWS = [
    ["Miete", "", "n fem", "", 0, _wty(["rent"], "Miete f (genitive Miete, plural Mieten)"), 1, ""],
    ["Mieten", "", "non-lemma", "", 0, [["Miete", ["plural"]]], 2, ""],
    ["anrufen", "", "v", "", 0, _wty(["vt to call, to ring (by telephone)"], "anrufen (class 7 strong)"), 3, ""],
    ["müssen", "", "v", "", 0, _wty(["to have to; must"], "müssen (preterite-present)"), 4, ""],
    ["muss", "", "non-lemma", "", 0, [["müssen", ["first/third-person singular present"]]], 5, ""],
]

JAPANESE_ROWS = [
    [
        "電車",
        "でんしゃ",
        "",
        "",
        0,
        [
            {
                "type": "structured-content",
                "content": [
                    {
                        "tag": "div",
                        "data": {"content": "sense-group"},
                        "content": [
                            {"tag": "span", "data": {"content": "part-of-speech-info"}, "content": "noun"},
                            {
                                "tag": "div",
                                "data": {"content": "sense"},
                                "content": {"tag": "ul", "data": {"content": "glossary"}, "content": [{"tag": "li", "content": "train"}, {"tag": "li", "content": "electric train"}]},
                            },
                        ],
                    }
                ],
            }
        ],
        1,
        "",
    ]
]


def make_zip(path: Path, lang: str, rows: list, title: str) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("index.json", json.dumps({"title": title, "format": 3, "revision": "test", "sourceLanguage": lang}))
        archive.writestr("term_bank_1.json", json.dumps(rows, ensure_ascii=False))
    return path
