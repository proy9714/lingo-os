"""Export everything to one file, and restore it on this or another computer.

A backup (`.lingo`, a zip) holds what can't be got back otherwise: the database (a consistent snapshot: words,
progress, history, settings, paired phones), your library (books, manga, your own media), recordings, reports,
imported CSVs, and this laptop's identity (data/device.json), so paired phones keep working after a restore.

Left out, because the app gets them again on its own: dictionaries and language models (downloaded again for every
added language after a restore), caches. API keys (.env) stay out too: they're secrets, paste them again in Settings.

Restoring first saves the current data as a backup in data/backups, then copies the backup's database into the live
one with SQLite's backup API (no restart needed), brings it up to this version's schema, and replaces the files.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, text

from app import __version__
from app.config import AppConfig
from app.timeutil import to_iso, utc_now

FORMAT = 1
SUFFIX = ".lingo"
FOLDERS = ("library", "recordings", "reports", "imports", "inbox")  # under the data folder
FILES = ("device.json",)
MAX_BYTES = 8 * 1024**3  # refuse anything larger uncompressed (a zip bomb, or the wrong file)


class BackupError(ValueError):
    pass


def _snapshot(cfg: AppConfig, target: Path) -> None:
    """A consistent copy of the live database, even while the app writes to it."""
    source = sqlite3.connect(cfg.db_path)
    try:
        dest = sqlite3.connect(target)
        try:
            source.backup(dest)
        finally:
            dest.close()
    finally:
        source.close()


def _summary(db: Path) -> dict[str, Any]:
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        def count(sql: str) -> int:
            try:
                return int(con.execute(sql).fetchone()[0])
            except sqlite3.Error:
                return 0

        try:
            languages = [r[0] for r in con.execute("SELECT code FROM languages WHERE enabled = 1 ORDER BY position")]
        except sqlite3.Error:
            languages = []
        return {
            "languages": languages,
            "words": count("SELECT COUNT(*) FROM user_words"),
            "sessions": count("SELECT COUNT(*) FROM activity_sessions"),
            "items": count("SELECT COUNT(*) FROM content_items"),
        }
    finally:
        con.close()


def export(cfg: AppConfig, target: Path | None = None) -> Path:
    """Write a backup file and return its path (data/backups/lingo-os-<date>.lingo unless `target` is given)."""
    stamp = utc_now().strftime("%Y-%m-%d-%H%M%S")
    target = target or cfg.data_dir / "backups" / f"lingo-os-{stamp}{SUFFIX}"
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "lingo.db"
        _snapshot(cfg, db)
        manifest = {"format": FORMAT, "app": "Lingo OS", "app_version": __version__, "created_at": to_iso(utc_now()),
                    **_summary(db)}
        partial = target.with_name(target.name + ".part")
        with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            zf.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
            zf.write(db, "lingo.db")
            for name in FILES:
                if (cfg.data_dir / name).is_file():
                    zf.write(cfg.data_dir / name, f"files/{name}")
            for folder in FOLDERS:
                root = cfg.data_dir / folder
                if not root.is_dir():
                    continue
                for path in sorted(root.rglob("*")):
                    if path.is_file():
                        zf.write(path, f"files/{folder}/{path.relative_to(root).as_posix()}")
        partial.replace(target)
    return target


def inspect(path: Path) -> dict[str, Any]:
    """What a backup holds, or BackupError saying why it can't be used."""
    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            if "manifest.json" not in names or "lingo.db" not in names:
                raise BackupError("That isn't a Lingo OS backup (it has no manifest or database).")
            if sum(i.file_size for i in zf.infolist()) > MAX_BYTES:
                raise BackupError("That backup is too large to restore.")
            for name in names:
                if name.startswith(("/", "\\")) or ".." in Path(name).parts:
                    raise BackupError("That backup contains unsafe file paths.")
            manifest = json.loads(zf.read("manifest.json"))
    except zipfile.BadZipFile as exc:
        raise BackupError("That file isn't a Lingo OS backup (not a zip file).") from exc
    if manifest.get("app") != "Lingo OS" or not isinstance(manifest.get("format"), int):
        raise BackupError("That isn't a Lingo OS backup.")
    if manifest["format"] > FORMAT:
        raise BackupError("That backup comes from a newer Lingo OS: update this one first.")
    return manifest


def restore(cfg: AppConfig, engine: Engine, path: Path) -> dict[str, Any]:
    """Replace this computer's data with a backup's. The current data is saved as a backup first."""
    from app.config import forget_added_languages
    from app.db import migrate
    from app.db.seed import seed
    from app.engine.profile import sync_baselines

    manifest = inspect(path)
    with engine.connect() as conn:
        running = conn.execute(text("SELECT COUNT(*) FROM jobs WHERE status = 'running'")).scalar()
    if running:
        raise BackupError("Something is running in the background (a download or a search): try again in a minute.")
    safety = export(cfg)  # the data as it was, in case this wasn't what you wanted
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        with zipfile.ZipFile(path) as zf:
            zf.extractall(tmp_dir)
        incoming = tmp_dir / "lingo.db"
        check = sqlite3.connect(incoming)
        try:
            if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise BackupError("The backup's database is damaged.")
        finally:
            check.close()
        migrate.apply_migrations(incoming, "main")  # a backup from an older version: bring it up to date first
        engine.dispose()  # no pooled connection keeps the old pages
        source, dest = sqlite3.connect(incoming), sqlite3.connect(cfg.db_path)
        try:
            source.backup(dest)
        finally:
            source.close()
            dest.close()
        engine.dispose()
        files = tmp_dir / "files"
        for folder in FOLDERS:
            current = cfg.data_dir / folder
            if current.exists():
                shutil.rmtree(current)
            if (files / folder).is_dir():
                shutil.copytree(files / folder, current)
        for name in FILES:
            if (files / name).is_file():
                shutil.copy2(files / name, cfg.data_dir / name)
    with engine.begin() as conn:
        seed(conn, cfg)
    with engine.begin() as conn:
        sync_baselines(conn, cfg)
    forget_added_languages()
    downloads = _download_missing(cfg, engine)
    return {"restored": True, "manifest": manifest, "previous_data": str(safety), "downloading": downloads}


def _download_missing(cfg: AppConfig, engine: Engine) -> list[str]:
    """Dictionaries and models aren't in a backup: get them for every language that needs them."""
    from app.db.engine import make_engine
    from app.jobs.runner import enqueue
    from app.services.languages import added_codes, dictionaries_of, install_job, model_ready

    started = []
    dict_engine = make_engine(cfg.dict_db_path)
    try:
        with engine.begin() as conn, dict_engine.connect() as dict_conn:
            for code in added_codes(conn):
                if model_ready(cfg, code) and dictionaries_of(dict_conn, code):
                    continue
                job = install_job(conn, code)
                if not (job and job["status"] in ("queued", "running")):
                    enqueue(conn, "install_language", {"code": code, "variant": None}, dedupe=False)
                started.append(code)
    finally:
        dict_engine.dispose()
    return started
