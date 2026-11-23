"""FastAPI app factory. Run with: uvicorn app.main:create_app --factory"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Engine

from app import __version__
from app.api import activity, imports, level, nlp, settings, stats, system, vocab
from app.config import AppConfig, load_config
from app.db import migrate
from app.db.engine import make_engine
from app.db.seed import seed
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


def create_app(cfg: AppConfig | None = None) -> FastAPI:
    cfg = cfg or load_config()
    app = FastAPI(title="Lingo OS", version=__version__)
    app.state.cfg = cfg
    app.state.engine = bootstrap(cfg)
    app.state.dict_engine = make_engine(cfg.dict_db_path)

    for module in (system, settings, stats, activity, imports, nlp, vocab, level):
        app.include_router(module.router)

    _serve_frontend(app, cfg.frontend_dist)
    return app


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
