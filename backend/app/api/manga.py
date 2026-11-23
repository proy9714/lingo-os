"""Manga: inbox import, pages with clickable text blocks, page images, volume vocabulary, OCR corrections."""

from __future__ import annotations

import shutil
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import Connection

from app.api.deps import get_cfg, get_conn, require_language
from app.config import AppConfig
from app.jobs import manga_ocr  # noqa: F401 - registers the OCR job
from app.jobs.runner import enqueue, latest_job
from app.services import content, manga

router = APIRouter(prefix="/api/manga", tags=["manga"])

UPLOAD_LIMIT = 1024 * 1024 * 1024  # 1 GB: a volume of high-resolution pages


class BlockFix(BaseModel):
    lines: list[str] = Field(min_length=1, max_length=40)


@router.get("/inbox")
def inbox(cfg: AppConfig = Depends(get_cfg)) -> dict[str, Any]:
    root = manga.ensure_inbox(cfg)
    return {"folder": str(root), "ocr_available": manga.mokuro_available()}


@router.post("/scan")
def scan(conn: Connection = Depends(get_conn), cfg: AppConfig = Depends(get_cfg)) -> dict[str, Any]:
    return manga.scan_inbox(conn, cfg)


@router.post("/upload", status_code=201)
async def upload(
    lang: str = Form("ja", min_length=2, max_length=8),
    file: UploadFile = File(...),
    conn: Connection = Depends(get_conn),
    cfg: AppConfig = Depends(get_cfg),
) -> dict[str, Any]:
    """A .zip or .cbz (pages, optionally with a .mokuro file) goes through the same path as the inbox."""
    require_language(conn, lang)
    name = file.filename or "volume.zip"
    if not name.lower().endswith((".zip", ".cbz")):
        raise HTTPException(status_code=422, detail="Upload a .zip or .cbz of the volume (with its .mokuro file if you have it).")
    folder = manga.ensure_inbox(cfg) / lang
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / name.replace("/", "_").replace("\\", "_")
    written = 0
    with target.open("wb") as out:
        while chunk := await file.read(1024 * 1024):
            written += len(chunk)
            if written > UPLOAD_LIMIT:
                out.close()
                target.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="Volumes up to 1 GB are supported.")
            out.write(chunk)
    return manga.scan_inbox(conn, cfg)


@router.get("/{item_id}/pages")
def page_list(item_id: int, conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    entries = manga.pages(conn, item_id)
    return {"total": len(entries), "pages": entries, "ocr_job": latest_job(conn, "ocr_manga")}


@router.get("/{item_id}/page/{number}")
def read_page(item_id: int, number: int, conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    try:
        return manga.page(conn, item_id, number)
    except content.ContentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{item_id}/image/{number}")
def image(item_id: int, number: int, conn: Connection = Depends(get_conn), cfg: AppConfig = Depends(get_cfg)) -> FileResponse:
    try:
        path = manga.image_path(cfg, conn, item_id, number)
    except content.ContentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path, headers={"Cache-Control": "private, max-age=604800"})


@router.get("/{item_id}/vocab")
def vocab(item_id: int, limit: int = Query(80, ge=1, le=500), conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    try:
        return manga.volume_vocab(conn, item_id, limit)
    except content.ContentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/blocks/{block_id}")
def fix_block(block_id: int, body: BlockFix, conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    try:
        return manga.correct_block(conn, block_id, body.lines)
    except content.ContentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{item_id}/ocr", status_code=202)
def ocr(item_id: int, conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    if not shutil.which("mokuro"):
        raise HTTPException(
            status_code=409,
            detail="OCR needs mokuro, which isn't installed. Run mokuro on the folder yourself, or ask for the manga extra.",
        )
    return {"job_id": enqueue(conn, "ocr_manga", {"item_id": item_id}, lane="gpu", dedupe=False)}
