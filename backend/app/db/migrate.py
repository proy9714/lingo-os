"""Numbered SQL migrations.

Each database has a folder of `NNNN_name.sql` files under `migrations/<kind>/`.
A file runs once, inside one transaction, and is recorded in `schema_migrations`.
Plain SQL suits SQLite better than an ORM migration tool: the schema is authored
in SQL (docs/schema.sql) and SQLite's ALTER support is limited anyway.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
KINDS = ("main", "dict")


def available(kind: str) -> list[Path]:
    if kind not in KINDS:
        raise ValueError(f"unknown migration kind: {kind}")
    return sorted((MIGRATIONS_DIR / kind).glob("*.sql"))


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version TEXT PRIMARY KEY,"
        " applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')))"
    )
    con.commit()
    return con


def applied(db_path: Path) -> list[str]:
    if not db_path.exists():
        return []
    con = _connect(db_path)
    try:
        return [row[0] for row in con.execute("SELECT version FROM schema_migrations ORDER BY version")]
    finally:
        con.close()


def apply_migrations(db_path: Path, kind: str) -> list[str]:
    """Apply pending migrations of `kind` to `db_path`. Returns the versions applied."""
    con = _connect(db_path)
    try:
        done = {row[0] for row in con.execute("SELECT version FROM schema_migrations")}
        newly_applied: list[str] = []
        for path in available(kind):
            version = path.stem
            if version in done:
                continue
            sql = path.read_text(encoding="utf-8")
            # executescript commits any open transaction first; wrapping the file in
            # BEGIN/COMMIT makes the migration and its bookkeeping row atomic.
            con.executescript(
                "BEGIN;\n" + sql + f"\nINSERT INTO schema_migrations(version) VALUES ('{version}');\nCOMMIT;"
            )
            newly_applied.append(version)
        return newly_applied
    finally:
        con.close()
