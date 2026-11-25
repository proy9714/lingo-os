"""Environment checks shared by `lingo doctor` and GET /api/system/status."""

from __future__ import annotations

import os
import shutil
import sys
from typing import Any

from app import __version__
from app.config import AppConfig
from app.db import migrate
from app.db.seed import hub_device_id


def run_checks(cfg: AppConfig) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str, required: bool = True) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail, "required": required})

    add("python", sys.version_info >= (3, 12), sys.version.split()[0])

    writable = cfg.data_dir.exists() and os.access(cfg.data_dir, os.W_OK)
    add("data folder", writable, str(cfg.data_dir))

    for kind, path in (("main", cfg.db_path), ("dict", cfg.dict_db_path)):
        done = migrate.applied(path)
        want = [p.stem for p in migrate.available(kind)]
        add(
            f"database ({kind})",
            done == want,
            f"{path.name}: {len(done)}/{len(want)} migrations" + ("" if done == want else " (run `lingo db migrate`)"),
        )

    built = (cfg.frontend_dist / "index.html").exists()
    add("frontend build", built, "frontend/dist" if built else "not built yet (npm run build)", required=False)

    ffmpeg = shutil.which("ffmpeg")
    add("ffmpeg", bool(ffmpeg), ffmpeg or "not on PATH (needed from Phase 2)", required=False)

    keys = {"Gemini": "GEMINI_API_KEY", "Claude": "ANTHROPIC_API_KEY", "ChatGPT": "OPENAI_API_KEY"}
    with_key = [name for name, env in keys.items() if os.environ.get(env)]
    add(
        "AI API key",
        bool(with_key),
        f"set for {', '.join(with_key)}" if with_key else "none (optional: Gemini, Claude or ChatGPT, in Settings or .env)",
        required=False,
    )

    tracker_ok = bool(cfg.tracker_path and cfg.tracker_path.is_dir())
    add(
        "Immersion Tracker folder",
        tracker_ok,
        str(cfg.tracker_path) if cfg.tracker_path else "not configured",
        required=False,
    )

    return {
        "version": __version__,
        "ok": all(c["ok"] for c in checks if c["required"]),
        "device_id": hub_device_id(cfg.data_dir),
        "data_dir": str(cfg.data_dir),
        "checks": checks,
    }
