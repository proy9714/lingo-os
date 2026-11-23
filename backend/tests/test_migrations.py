"""The migration files must build exactly the schema documented in docs/schema.sql."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app.config import ROOT
from app.db import migrate

IGNORED = {"schema_migrations", "sqlite_sequence"}


def _tables(con: sqlite3.Connection) -> set[str]:
    names = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    return {n for n in names if n not in IGNORED and not n.startswith("content_fts_")}


def _columns(con: sqlite3.Connection, table: str) -> list[tuple]:
    # (name, type, notnull, default, pk) for every column, in order
    return [tuple(row[1:]) for row in con.execute(f"PRAGMA table_info({table})")]


def test_migrations_build_the_reference_schema(tmp_path: Path) -> None:
    main_db, dict_db = tmp_path / "lingo.db", tmp_path / "dictionaries.db"
    assert migrate.apply_migrations(main_db, "main") == ["0001_initial", "0002_job_kinds"]
    assert migrate.apply_migrations(dict_db, "dict") == ["0001_initial"]

    reference = sqlite3.connect(":memory:")
    reference.executescript((ROOT / "docs" / "schema.sql").read_text(encoding="utf-8"))
    built = {name: sqlite3.connect(path) for name, path in (("main", main_db), ("dict", dict_db))}

    built_tables = _tables(built["main"]) | _tables(built["dict"])
    assert built_tables == _tables(reference)
    for table in sorted(built_tables):
        con = built["main"] if table in _tables(built["main"]) else built["dict"]
        assert _columns(con, table) == _columns(reference, table), table


def test_migrations_run_once(tmp_path: Path) -> None:
    db = tmp_path / "lingo.db"
    migrate.apply_migrations(db, "main")
    assert migrate.apply_migrations(db, "main") == []
    assert migrate.applied(db) == ["0001_initial", "0002_job_kinds"]


def test_constraints_match_the_reference_schema(tmp_path: Path) -> None:
    """Column lists alone miss CHECK lists (a missing job kind once broke the history button): compare the DDL too."""
    db = tmp_path / "lingo.db"
    migrate.apply_migrations(db, "main")
    reference = sqlite3.connect(":memory:")
    reference.executescript((ROOT / "docs" / "schema.sql").read_text(encoding="utf-8"))
    built = sqlite3.connect(db)
    strip = lambda sql: [line.split("--")[0] for line in sql.splitlines()]  # noqa: E731
    for table in ("jobs",):
        ref = " ".join(" ".join(strip(reference.execute(
            "SELECT sql FROM sqlite_master WHERE name = :t", {"t": table}).fetchone()[0])).split())
        got = " ".join(" ".join(strip(built.execute(
            "SELECT sql FROM sqlite_master WHERE name = :t", {"t": table}).fetchone()[0])).split())
        assert got.replace(f'"{table}"', table).replace(f"{table}_new", table) == ref
