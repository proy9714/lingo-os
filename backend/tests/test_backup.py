"""Export everything to one file and restore it."""

from __future__ import annotations

import io
import json
import zipfile

from sqlalchemy import text

from app.db import settings_store
from app.services import backup


def test_export_then_restore_brings_everything_back(client) -> None:
    cfg = client.app.state.cfg
    engine = client.app.state.engine
    with engine.begin() as conn:
        settings_store.put(conn, "marker", "before")
    (cfg.data_dir / "library" / "books").mkdir(parents=True, exist_ok=True)
    (cfg.data_dir / "library" / "books" / "mine.txt").write_text("my book", encoding="utf-8")

    response = client.get("/api/data/export")
    assert response.status_code == 200 and response.headers["content-type"] == "application/zip"
    blob = response.content
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        names = set(zf.namelist())
        manifest = json.loads(zf.read("manifest.json"))
    assert {"manifest.json", "lingo.db", "files/library/books/mine.txt"} <= names
    assert not any(n.startswith(("files/models", "files/dictionaries", "files/cache")) for n in names)
    assert manifest["format"] == backup.FORMAT and manifest["app"] == "Lingo OS"

    # things change after the backup…
    with engine.begin() as conn:
        settings_store.put(conn, "marker", "after")
    (cfg.data_dir / "library" / "books" / "mine.txt").unlink()
    (cfg.data_dir / "library" / "stray.txt").write_text("added later", encoding="utf-8")

    # …and the backup brings them back
    restored = client.post("/api/data/import", files={"file": ("lingo-os.lingo", blob, "application/zip")})
    assert restored.status_code == 200, restored.text
    body = restored.json()
    assert body["restored"] and body["previous_data"].endswith(".lingo")
    with engine.connect() as conn:
        assert settings_store.get(conn, "marker") == "before"
    assert (cfg.data_dir / "library" / "books" / "mine.txt").read_text(encoding="utf-8") == "my book"
    assert not (cfg.data_dir / "library" / "stray.txt").exists()

    # the data as it was just before the restore was kept
    with zipfile.ZipFile(body["previous_data"]) as zf:
        assert "files/library/stray.txt" in zf.namelist()


def test_bad_files_are_refused(client) -> None:
    assert client.post("/api/data/import", files={"file": ("x.lingo", b"not a zip", "application/zip")}).status_code == 422
    other = io.BytesIO()
    with zipfile.ZipFile(other, "w") as zf:
        zf.writestr("hello.txt", "hi")
    assert client.post("/api/data/import", files={"file": ("x.lingo", other.getvalue(), "application/zip")}).status_code == 422
    sneaky = io.BytesIO()
    with zipfile.ZipFile(sneaky, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"app": "Lingo OS", "format": 1}))
        zf.writestr("lingo.db", b"")
        zf.writestr("../outside.txt", "no")
    refused = client.post("/api/data/import", files={"file": ("x.lingo", sneaky.getvalue(), "application/zip")})
    assert refused.status_code == 422 and "unsafe" in refused.json()["detail"]


def test_a_restore_waits_for_running_jobs(client) -> None:
    with client.app.state.engine.begin() as conn:
        conn.execute(text("INSERT INTO jobs (kind, status, payload_json) VALUES ('rescore', 'running', '{}')"))
    blob = client.get("/api/data/export").content
    response = client.post("/api/data/import", files={"file": ("x.lingo", blob, "application/zip")})
    assert response.status_code == 422 and "background" in response.json()["detail"]
