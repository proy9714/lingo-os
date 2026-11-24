"""Languages you learn: the catalogue, adding one (downloads in the background), its regional variety, removing it."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Connection

from app.api.deps import get_cfg, get_conn, get_dict_conn
from app.config import AppConfig
from app.services import languages

router = APIRouter(prefix="/api/languages", tags=["languages"])


@router.get("/catalog")
def catalog(
    conn: Connection = Depends(get_conn), dict_conn: Connection = Depends(get_dict_conn), cfg: AppConfig = Depends(get_cfg)
) -> list[dict[str, Any]]:
    """Every language Lingo OS can teach, most spoken first, with whether you've added it and what it would download."""
    return languages.catalog(conn, dict_conn, cfg)


class AddLanguage(BaseModel):
    code: str = Field(min_length=2, max_length=8)
    variant: str | None = Field(default=None, max_length=16)


@router.post("", status_code=202)
def add(
    body: AddLanguage,
    conn: Connection = Depends(get_conn),
    dict_conn: Connection = Depends(get_dict_conn),
    cfg: AppConfig = Depends(get_cfg),
) -> dict[str, Any]:
    try:
        return languages.add_language(conn, dict_conn, cfg, body.code, body.variant)
    except languages.LanguageError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class LanguagePatch(BaseModel):
    variant: str = Field(min_length=1, max_length=16)


@router.patch("/{code}")
def patch(code: str, body: LanguagePatch, conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    try:
        languages.set_variant(conn, code, body.variant)
    except (languages.LanguageError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"code": code, "variant": body.variant}


@router.delete("/{code}")
def remove(code: str, conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    try:
        return languages.remove_language(conn, code)
    except languages.LanguageError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
