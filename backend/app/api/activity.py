from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Connection

from app.api.deps import get_conn, require_language
from app.services import activity, tracking

router = APIRouter(prefix="/api", tags=["activity"])


class ManualLog(BaseModel):
    language: str = Field(min_length=2, max_length=8)
    activity: str
    minutes: int = Field(ge=1, le=720)
    day: date | None = None
    title: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=2000)


class Heartbeat(BaseModel):
    lang: str = Field(min_length=2, max_length=8)
    activity: str = Field(max_length=20)
    session: str = Field(pattern=r"^[A-Za-z0-9-]{8,64}$")
    seconds: int = Field(ge=0, le=120)
    content_item_id: int | None = None
    position_ms: int | None = Field(default=None, ge=0)
    duration_ms: int | None = Field(default=None, ge=0)


class StopSession(BaseModel):
    session: str = Field(pattern=r"^[A-Za-z0-9-]{8,64}$")


@router.post("/activity/heartbeat")
def heartbeat(body: Heartbeat, conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    require_language(conn, body.lang)
    try:
        return tracking.heartbeat(
            conn,
            lang=body.lang,
            activity=body.activity,
            session=body.session,
            seconds=body.seconds,
            content_item_id=body.content_item_id,
            position_ms=body.position_ms,
            duration_ms=body.duration_ms,
        )
    except tracking.TrackingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/activity/stop")
def stop(body: StopSession, conn: Connection = Depends(get_conn)) -> dict[str, bool]:
    tracking.stop(conn, body.session)
    return {"stopped": True}


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
