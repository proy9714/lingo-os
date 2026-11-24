"""FastAPI app factory. Run with: uvicorn app.main:create_app --factory"""

from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Engine

from app import __version__
from app.ai.config import load_ai_config
from app.ai.gateway import Gateway
from app.api import activity, ai, automation, content, devices, imports, level, manga, nlp, settings, shadowing, stats, system, tutor, vocab
from app.jobs.runner import Runner
from app.config import AppConfig, load_config
from app.db import migrate
from app.db.engine import make_engine
from app.db import settings_store
from app.db.seed import seed
from app.sync.hub import SYNC_PORT
from app.sync.server import Listener
from app.engine.profile import sync_baselines


def bootstrap(cfg: AppConfig) -> Engine:
    """Create the data folder, apply migrations to both databases and seed defaults."""
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    migrate.apply_migrations(cfg.db_path, "main")
    migrate.apply_migrations(cfg.dict_db_path, "dict")
    engine = make_engine(cfg.db_path)
    with engine.begin() as conn:
        seed(conn, cfg)
        sync_baselines(conn, cfg)
    return engine


def create_app(cfg: AppConfig | None = None, *, run_jobs: bool = True) -> FastAPI:
    cfg = cfg or load_config()
    engine = bootstrap(cfg)

    @asynccontextmanager
    async def lifespan(app_: FastAPI):
        runner = Runner(engine, cfg) if run_jobs else None
        if runner:
            runner.start()
        with engine.connect() as conn:  # phone sync listens on the Wi-Fi only when turned on in Settings
            sync_on = run_jobs and bool(settings_store.get(conn, "sync.enabled", False))
            port = int(settings_store.get(conn, "sync.port", SYNC_PORT))
        if sync_on:
            devices.start_listener(app_, cfg, port)
        if runner:
            # in a thread: ranking a big catalogue the first time takes a few seconds, the server shouldn't wait
            threading.Thread(target=_top_up_on_start, args=(engine, cfg.default_language), daemon=True).start()
        yield
        app_.state.sync_listener.stop()
        if runner:
            runner.stop()

    app = FastAPI(title="Lingo OS", version=__version__, lifespan=lifespan)
    app.state.cfg = cfg
    app.state.engine = engine
    app.state.dict_engine = make_engine(cfg.dict_db_path)
    app.state.ai = Gateway(load_ai_config(cfg.root), engine)
    app.state.sync_listener = Listener()

    for module in (system, settings, stats, activity, imports, nlp, vocab, level, content, ai, manga, tutor, shadowing, automation, devices):
        app.include_router(module.router)

    _serve_frontend(app, cfg.frontend_dist)
    return app


def _top_up_on_start(engine: Engine, default_language: str) -> None:
    """Opening the app starts the background search for new content at once (if suggestions are low and it's due),
    so new finds trickle in while you use the app instead of waiting for a page to ask."""
    from app.services import topup

    try:
        with engine.begin() as conn:
            lang = settings_store.get(conn, "active_language", default_language)
            topup.maybe_top_up(conn, lang)
    except Exception:  # noqa: BLE001 - never stop the app from starting over a search
        logging.getLogger(__name__).exception("starting the background search failed")


def _serve_frontend(app: FastAPI, dist: Path) -> None:
    """Serve the built single-page app, falling back to index.html for client-side routes."""
    index = dist / "index.html"
    if not index.exists():
        return
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")
    root = dist.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path.startswith("api/") or path == "api":
            raise HTTPException(status_code=404)
        candidate = (dist / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return FileResponse(index)
