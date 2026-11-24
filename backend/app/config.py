"""Configuration: config/*.yaml plus .env, resolved against the project root."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class LanguageConfig:
    """A language this learner has added, with its catalogue details (app/languages/registry.py)."""

    code: str
    name: str
    native_name: str
    accent: str
    writing_mode: str = "horizontal-tb"
    direction: str = "ltr"
    accent_ink: str = "#1a1300"
    variant: str | None = None


def language_config(code: str, variant: str | None = None) -> LanguageConfig:
    from app.languages.registry import spec

    s = spec(code)
    return LanguageConfig(
        code=s.code, name=s.name, native_name=s.native_name, accent=s.accent, writing_mode=s.writing_mode,
        direction=s.direction, accent_ink=s.accent_ink, variant=s.variant(variant).id,
    )


def forget_added_languages() -> None:
    """Kept for callers that change the languages; the list is read fresh every time."""


def _added_languages(db_path: Path, starting: tuple[str, ...]) -> tuple[LanguageConfig, ...]:
    import sqlite3

    from app.languages.registry import get

    # read fresh each time (about a millisecond): a cached list could go stale while a request that adds a language
    # is still in its transaction
    rows: list[tuple[str, str | None]] = []
    if db_path.exists():
        con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
        try:
            try:
                rows = con.execute("SELECT code, variant FROM languages WHERE enabled = 1 ORDER BY position, rowid").fetchall()
            except sqlite3.OperationalError:  # before migration 0004
                rows = [(r[0], None) for r in con.execute("SELECT code FROM languages WHERE enabled = 1 ORDER BY rowid")]
        except sqlite3.OperationalError:  # no languages table yet
            rows = []
        finally:
            con.close()
        found = tuple(language_config(code, variant) for code, variant in rows if get(code))
    else:
        found = tuple(language_config(code) for code in starting if get(code))
    return found


@dataclass(frozen=True)
class AppConfig:
    root: Path
    data_dir: Path
    host: str
    port: int
    starting_languages: tuple[str, ...]  # added to a brand-new database; empty: the first run asks
    default_language: str
    default_goal_minutes: int
    tracker_path: Path | None
    baselines: dict[str, Any]

    @property
    def db_path(self) -> Path:
        return self.data_dir / "lingo.db"

    @property
    def dict_db_path(self) -> Path:
        return self.data_dir / "dictionaries.db"

    @property
    def languages(self) -> tuple[LanguageConfig, ...]:
        """The languages this learner has added (Settings → Languages), in the order they were added."""
        return _added_languages(self.db_path, self.starting_languages)

    @property
    def language_codes(self) -> list[str]:
        return [lang.code for lang in self.languages]

    @property
    def frontend_dist(self) -> Path:
        return self.root / "frontend" / "dist"


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _resolve(root: Path, value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _merge(base: dict[str, Any], local: dict[str, Any]) -> dict[str, Any]:
    """Local values win; nested sections are merged key by key."""
    out = dict(base)
    for key, value in local.items():
        out[key] = _merge(out[key], value) if isinstance(value, dict) and isinstance(out.get(key), dict) else value
    return out


def load_config(root: Path = ROOT, data_dir: str | Path | None = None) -> AppConfig:
    """Load settings. `data_dir` (or LINGO_DATA_DIR) overrides config/app.yaml."""
    load_dotenv(root / ".env", override=False)
    # config/app.local.yaml (git-ignored) holds this computer's own settings, such as a tracker folder
    app_yaml = _merge(_read_yaml(root / "config" / "app.yaml"), _read_yaml(root / "config" / "app.local.yaml"))
    baselines = _read_yaml(root / "config" / "baselines.yaml")

    chosen_data_dir = data_dir or os.environ.get("LINGO_DATA_DIR") or app_yaml.get("data_dir", "data")
    server = app_yaml.get("server", {})
    defaults = app_yaml.get("defaults", {})
    tracker = (app_yaml.get("immersion_tracker") or {}).get("path")

    # `languages:` lists codes (or {code: …} entries, as older configs did) to add to a brand-new database
    starting = tuple(item["code"] if isinstance(item, dict) else str(item) for item in app_yaml.get("languages") or [])

    return AppConfig(
        root=root,
        data_dir=_resolve(root, chosen_data_dir),
        host=server.get("host", "127.0.0.1"),
        port=int(server.get("port", 8787)),
        starting_languages=starting,
        default_language=defaults.get("active_language") or (starting[0] if starting else "de"),
        default_goal_minutes=int(defaults.get("daily_goal_minutes", 60)),
        tracker_path=_resolve(root, tracker) if tracker else None,
        baselines=baselines,
    )
