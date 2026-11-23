from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Connection

from app.api.deps import get_conn
from app.services import activity

router = APIRouter(prefix="/api", tags=["activity"])


class ManualLog(BaseModel):
    language: str = Field(min_length=2, max_length=8)
    activity: str
    minutes: int = Field(ge=1, le=720)
    day: date | None = None
    title: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=2000)


@router.get("/activity/kinds")
def kinds() -> list[dict[str, str]]:
    return [{"activity": a, "modality": activity.MODALITY[a]} for a in activity.MANUAL_ACTIVITIES]


@router.post("/activity/manual", status_code=201)
def log_manual(body: ManualLog, conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    try:
        return activity.log_manual(
            conn,
            language=body.language,
            activity=body.activity,
            minutes=body.minutes,
            day=body.day,
            title=body.title,
            notes=body.notes,
        )
    except activity.ActivityError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
