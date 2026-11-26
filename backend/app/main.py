"""FastAPI app factory. Run with: uvicorn app.main:create_app --factory"""

from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware
from sqlalchemy import Engine

from app import __version__
from app.ai.config import load_ai_config
from app.ai.gateway import Gateway
from app.api import activity, ai, automation, content, data, devices, imports, level, manga, nlp, settings, shadowing, stats, system, tts, tutor, vocab
from app.api import offline_media
from app.api import languages as languages_api
from app.api import search as search_api
from app.jobs import languages as _language_jobs  # noqa: F401 - registers install_language
from app.jobs.runner import Runner
from app.config import AppConfig, load_config
from app.db import migrate
from app.db.engine import make_engine
from app.db import settings_store
from app.db.seed import seed
from app.access import AccessMiddleware
from app.etag import ETagMiddleware
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
    with engine.begin() as conn:  # after the seed is committed: cfg.languages reads the languages it added
        sync_baselines(conn, cfg)
    _wire_languages(cfg)
    return engine


def _wire_languages(cfg: AppConfig) -> None:
    """Language packs find downloaded models in data/models, and check weak lemmas against the dictionaries."""
    from app.dictionary.lookup import lemma_resolver
    from app.languages import set_lemma_resolver
    from app.languages.spacy_pack import MODELS_DIR

    MODELS_DIR[:] = [cfg.data_dir / "models"]
    set_lemma_resolver(lemma_resolver(make_engine(cfg.dict_db_path)))


def create_app(cfg: AppConfig | None = None, *, run_jobs: bool = True) -> FastAPI:
    cfg = cfg or load_config()
    engine = bootstrap(cfg)

    @asynccontextmanager
    async def lifespan(app_: FastAPI):
        runner = Runner(engine, cfg) if run_jobs else None
        if runner:
            runner.start()
        with engine.connect() as conn:  # phone sync listens on the Wi-Fi only when turned on in Settings
            sync_on = run_jobs and devices.phone_sync_allowed() and bool(settings_store.get(conn, "sync.enabled", False))
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

    for module in (system, settings, stats, activity, imports, nlp, vocab, level, content, ai, manga, tutor, shadowing, automation, devices, tts, languages_api, search_api, data, offline_media):
        app.include_router(module.router)

    # an unchanged answer is "304 Not Modified" instead of the whole body (app/etag.py); added first, so it sees the
    # answer before it's compressed
    app.add_middleware(ETagMiddleware)
    # compress JSON, scripts and styles (often 70-90% smaller); audio and pictures are already compressed
    app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)
    if cfg.access_token:  # a server: sign in first (app/access.py); outermost, so nothing answers before it
        secure = bool(cfg.public_url and cfg.public_url.startswith("https://"))
        app.add_middleware(AccessMiddleware, token=cfg.access_token, secure_cookie=secure)
    elif cfg.host not in LOOPBACK:
        logging.getLogger(__name__).warning(
            "Lingo OS is answering %s without LINGO_ACCESS_TOKEN: anyone who can reach it can read and change your data. "
            "Keep it on a private network (Tailscale) or set a token (docs/DEPLOY.md).",
            cfg.host,
        )
    if cfg.sync_on_main:
        # a server: phones sync through this port (one address, one HTTPS certificate) instead of the Wi-Fi listener
        from app.sync.server import create_sync_app

        app.mount("/sync", create_sync_app(app, engine, cfg, base=""))
    _serve_frontend(app, cfg.frontend_dist)
    return app


LOOPBACK = {"127.0.0.1", "localhost", "::1"}


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
        app.mount("/assets", ImmutableFiles(directory=dist / "assets"), name="assets")
    root = dist.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path.startswith("api/") or path == "api":
            raise HTTPException(status_code=404)
        candidate = (dist / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate, headers={"Cache-Control": "public, max-age=86400"})  # icons and the like
        # the page itself is always checked (a cheap 304), so a new version of the app shows on the next load
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


class ImmutableFiles(StaticFiles):
    """Vite names every built file after its contents, so a file never changes: browsers may keep it for a year."""

    def file_response(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response
