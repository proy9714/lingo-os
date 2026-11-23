"""`lingo serve` serves the built SPA: files as-is, client routes fall back to index.html, /api stays JSON."""

from __future__ import annotations

import dataclasses
import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import ROOT, AppConfig
from app.main import create_app


def test_built_frontend_is_served(cfg: AppConfig, tmp_path: Path) -> None:
    root = tmp_path / "project"
    dist = root / "frontend" / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><div id=root></div>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log('ok')", encoding="utf-8")
    (dist / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    shutil.copytree(ROOT / "config", root / "config")

    with TestClient(create_app(dataclasses.replace(cfg, root=root))) as client:
        assert "id=root" in client.get("/").text
        assert "id=root" in client.get("/watch").text  # client-side route
        assert client.get("/assets/app.js").text == "console.log('ok')"
        assert client.get("/favicon.svg").status_code == 200
        assert client.get("/api/health").json()["ok"] is True
        assert client.get("/api/does-not-exist").status_code == 404
        assert "id=root" in client.get("/..%2F..%2Fconfig%2Fapp.yaml").text  # no escaping the dist folder
