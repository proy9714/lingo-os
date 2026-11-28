from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine, event

# busy_timeout: a job lane may hold the write lock for a few seconds while it scores a text; others wait for it
PRAGMAS = ("foreign_keys=ON", "journal_mode=WAL", "synchronous=NORMAL", "busy_timeout=15000")


def make_engine(path: Path) -> Engine:
    """Engine for one SQLite file with the project's connection PRAGMAs applied."""
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path.as_posix()}")

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn, _record):  # noqa: ANN001 - DB-API objects
        cursor = dbapi_conn.cursor()
        for pragma in PRAGMAS:
            cursor.execute(f"PRAGMA {pragma}")
        cursor.close()

    return engine
