from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Connection, text

from app.api.deps import get_cfg, get_conn, get_dict_conn, require_language
from app.config import AppConfig
from app.engine.profile import get_profile, total_seconds
from app.level import ctest, vocab_test
from app.services.estimate import hours_estimate

router = APIRouter(prefix="/api/level", tags=["level"])


class KnownAnswer(BaseModel):
    item_id: int
    known: bool


class MeaningAnswer(BaseModel):
    item_id: int
    choice: int | None = Field(default=None, ge=0, le=5)  # None = "not sure"


class CTestAnswers(BaseModel):
    answers: dict[int, str] = Field(default_factory=dict)


@router.get("/{lang}/overview")
def overview(lang: str, conn: Connection = Depends(get_conn), cfg: AppConfig = Depends(get_cfg)) -> dict[str, Any]:
    require_language(conn, lang)
    skills = {
        r[0]: {"band": r[1], "band_low": r[2], "band_high": r[3], "last_tested_at": r[4]}
        for r in conn.execute(
            text("SELECT skill, band, band_low, band_high, last_tested_at FROM skill_estimates WHERE language_code = :l"),
            {"l": lang},
        ).all()
    }
    history = []
    for r in conn.execute(
        text(
            "SELECT id, skill, method, status, result_json, started_at, finished_at FROM assessments "
            "WHERE language_code = :l AND status = 'done' ORDER BY finished_at DESC LIMIT 10"
        ),
        {"l": lang},
    ).all():
        history.append(
            {"id": r[0], "skill": r[1], "method": r[2], "result": json.loads(r[4] or "{}"), "finished_at": r[6]}
        )
    for entry in history:  # newest result per skill
        skills.setdefault(entry["skill"], {}).setdefault("result", entry["result"])
    return {
        "language": lang,
        "profile": get_profile(conn, lang),
        "hours_estimate": hours_estimate(lang, total_seconds(conn, lang) / 3600, cfg.baselines),
        "skills": skills,
        "history": history,
        "ctest_available": ctest.available(lang),
    }


@router.post("/{lang}/vocab/start")
def vocab_start(lang: str, conn: Connection = Depends(get_conn), dict_conn: Connection = Depends(get_dict_conn)) -> dict[str, Any]:
    require_language(conn, lang)
    try:
        return vocab_test.start(conn, dict_conn, lang)
    except vocab_test.TestError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/vocab/{assessment_id}/answer")
def vocab_answer(
    assessment_id: int,
    body: KnownAnswer,
    conn: Connection = Depends(get_conn),
    dict_conn: Connection = Depends(get_dict_conn),
    cfg: AppConfig = Depends(get_cfg),
) -> dict[str, Any]:
    try:
        return vocab_test.answer(conn, dict_conn, cfg, assessment_id, body.item_id, body.known)
    except vocab_test.TestError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/vocab/{assessment_id}/meaning")
def vocab_meaning(
    assessment_id: int,
    body: MeaningAnswer,
    conn: Connection = Depends(get_conn),
    dict_conn: Connection = Depends(get_dict_conn),
    cfg: AppConfig = Depends(get_cfg),
) -> dict[str, Any]:
    try:
        return vocab_test.meaning(conn, dict_conn, cfg, assessment_id, body.item_id, body.choice)
    except vocab_test.TestError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/vocab/{assessment_id}/finish")
def vocab_finish(assessment_id: int, conn: Connection = Depends(get_conn), cfg: AppConfig = Depends(get_cfg)) -> dict[str, Any]:
    try:
        return vocab_test.finish(conn, cfg, assessment_id)
    except vocab_test.TestError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{lang}/ctest/start")
def ctest_start(lang: str, conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    require_language(conn, lang)
    try:
        return ctest.start(conn, lang)
    except ctest.CTestError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/ctest/{assessment_id}/submit")
def ctest_submit(
    assessment_id: int, body: CTestAnswers, conn: Connection = Depends(get_conn), cfg: AppConfig = Depends(get_cfg)
) -> dict[str, Any]:
    try:
        return ctest.submit(conn, cfg, assessment_id, body.answers)
    except ctest.CTestError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
