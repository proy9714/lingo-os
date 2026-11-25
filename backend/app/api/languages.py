"""Languages you learn: the catalogue, adding one (downloads in the background), its regional variety, removing it."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import Connection

from app.api.deps import get_cfg, get_conn, get_dict_conn
from app.config import AppConfig
from app.services import languages, starting

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


# ------------------------------------------------------------------ your starting point in a language


def _known(conn: Connection, code: str) -> str:
    from sqlalchemy import text

    if not conn.execute(text("SELECT 1 FROM languages WHERE code = :c"), {"c": code}).first():
        raise HTTPException(status_code=404, detail=f"'{code}' isn't one of your languages")
    return code


@router.get("/history-template.csv", response_class=PlainTextResponse)
def history_template() -> PlainTextResponse:
    """An example of the simple CSV format, to fill in and import."""
    return PlainTextResponse(
        starting.TEMPLATE, media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="lingo-os-history-template.csv"'},
    )


@router.get("/{code}/start")
def start(code: str, conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    return starting.summary(conn, _known(conn, code))


class LevelBody(BaseModel):
    level: str | None = Field(default=None, max_length=4)


@router.put("/{code}/level")
def set_level(code: str, body: LevelBody, conn: Connection = Depends(get_conn), cfg: AppConfig = Depends(get_cfg)) -> dict[str, Any]:
    """The level you think you're at (CEFR, or JLPT for Japanese); null clears it."""
    try:
        return starting.set_level(conn, cfg, _known(conn, code), body.level)
    except starting.StartingPointError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class ExamBody(BaseModel):
    exam: str | None = Field(default=None, max_length=40)  # null removes it
    level: str | None = Field(default=None, max_length=40)
    passed_on: str | None = Field(default=None, max_length=10)  # YYYY-MM-DD


@router.put("/{code}/exam")
def set_exam(code: str, body: ExamBody, conn: Connection = Depends(get_conn), cfg: AppConfig = Depends(get_cfg)) -> dict[str, Any]:
    """An official exam you passed (Goethe B1, DELE B2, JLPT N3…): a firmer starting point than a level you chose."""
    try:
        return starting.set_exam(conn, cfg, _known(conn, code), body.exam, body.level, body.passed_on)
    except starting.StartingPointError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class BaselineBody(BaseModel):
    hours: float = Field(ge=0, le=starting.MAX_BASELINE_HOURS)


@router.put("/{code}/baseline")
def set_baseline(code: str, body: BaselineBody, conn: Connection = Depends(get_conn), cfg: AppConfig = Depends(get_cfg)) -> dict[str, Any]:
    """Hours spent in the language before Lingo OS (imported hours count toward it)."""
    try:
        return starting.set_baseline_hours(conn, cfg, _known(conn, code), body.hours)
    except starting.StartingPointError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


HISTORY_LIMIT = 20 * 1024 * 1024


@router.post("/{code}/history")
def import_history(
    code: str, file: UploadFile = File(...), conn: Connection = Depends(get_conn), cfg: AppConfig = Depends(get_cfg)
) -> dict[str, Any]:
    """Import a CSV of what you watched, read or listened to (Immersion Tracker or the simple format)."""
    data = file.file.read(HISTORY_LIMIT + 1)  # a plain function: runs on a worker thread, not the event loop
    if len(data) > HISTORY_LIMIT:
        raise HTTPException(status_code=413, detail="CSV files up to 20 MB are supported.")
    try:
        return starting.import_csv(conn, cfg, _known(conn, code), file.filename or "history.csv", data)
    except (starting.StartingPointError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{code}/history")
def history(code: str, conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    return starting.history(conn, _known(conn, code))
