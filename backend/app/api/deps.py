from __future__ import annotations

from collections.abc import Iterator

from fastapi import HTTPException, Request
from sqlalchemy import Connection, text

from app.config import AppConfig


def get_cfg(request: Request) -> AppConfig:
    return request.app.state.cfg


def get_conn(request: Request) -> Iterator[Connection]:
    """One transaction per request: committed on success, rolled back on error."""
    with request.app.state.engine.begin() as conn:
        yield conn


def get_dict_conn(request: Request) -> Iterator[Connection]:
    """Connection to dictionaries.db (separate file, read-mostly)."""
    with request.app.state.dict_engine.begin() as conn:
        yield conn


def require_language(conn: Connection, code: str) -> str:
    if not conn.execute(text("SELECT 1 FROM languages WHERE code = :c AND enabled = 1"), {"c": code}).first():
        raise HTTPException(status_code=404, detail=f"unknown language '{code}'")
    return code
