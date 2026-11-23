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
    code: str
    name: str
    native_name: str
    accent: str
    writing_mode: str = "horizontal-tb"


@dataclass(frozen=True)
class AppConfig:
    root: Path
    data_dir: Path
    host: str
    port: int
    languages: tuple[LanguageConfig, ...]
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


def load_config(root: Path = ROOT, data_dir: str | Path | None = None) -> AppConfig:
    """Load settings. `data_dir` (or LINGO_DATA_DIR) overrides config/app.yaml."""
    load_dotenv(root / ".env", override=False)
    app_yaml = _read_yaml(root / "config" / "app.yaml")
    baselines = _read_yaml(root / "config" / "baselines.yaml")

    chosen_data_dir = data_dir or os.environ.get("LINGO_DATA_DIR") or app_yaml.get("data_dir", "data")
    server = app_yaml.get("server", {})
    defaults = app_yaml.get("defaults", {})
    tracker = (app_yaml.get("immersion_tracker") or {}).get("path")

    languages = tuple(
        LanguageConfig(
            code=item["code"],
            name=item["name"],
            native_name=item.get("native_name", item["name"]),
            accent=item.get("accent", "#f5b443"),
            writing_mode=item.get("writing_mode", "horizontal-tb"),
        )
        for item in app_yaml.get("languages", [])
    )
    if not languages:
        raise ValueError("config/app.yaml must list at least one language")

    return AppConfig(
        root=root,
        data_dir=_resolve(root, chosen_data_dir),
        host=server.get("host", "127.0.0.1"),
        port=int(server.get("port", 8787)),
        languages=languages,
        default_language=defaults.get("active_language", languages[0].code),
        default_goal_minutes=int(defaults.get("daily_goal_minutes", 60)),
        tracker_path=_resolve(root, tracker) if tracker else None,
        baselines=baselines,
    )
