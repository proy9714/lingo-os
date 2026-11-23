from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import Connection, text

from app.api.deps import get_cfg, get_conn, require_language
from app.config import AppConfig
from app.engine.evidence import content_evidence
from app.ingest import documents
from app.ingest.youtube import YouTubeError, fetch_captions, fetch_info, parse_video_id
from app.jobs import analysis, history  # noqa: F401 - registers the job handlers
from app.jobs.runner import enqueue, get_job, latest_job
from app.services import content, reading
from app.services.recommend import up_next

router = APIRouter(prefix="/api", tags=["content"])


class AddYouTube(BaseModel):
    lang: str = Field(min_length=2, max_length=8)
    url: str = Field(min_length=11, max_length=500)


class HistoryRequest(BaseModel):
    lang: str | None = Field(default=None, max_length=8)
    limit: int | None = Field(default=None, ge=1, le=2000)


class AddArticle(BaseModel):
    lang: str = Field(min_length=2, max_length=8)
    url: str = Field(min_length=8, max_length=1000, pattern=r"^https?://")


class AddText(BaseModel):
    lang: str = Field(min_length=2, max_length=8)
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=200_000)


class PageProgress(BaseModel):
    page: int = Field(ge=1)
    total: int = Field(ge=1)


UPLOAD_LIMIT = 80 * 1024 * 1024


@router.get("/content")
def list_content(
    lang: str = Query(..., min_length=2, max_length=8),
    q: str | None = Query(None, max_length=100),
    kind: str | None = Query(None, pattern="^(youtube|local)$"),
    shelf: str = Query("watch", pattern="^(watch|read|manga)$"),
    limit: int = Query(60, ge=1, le=300),
    offset: int = Query(0, ge=0),
    conn: Connection = Depends(get_conn),
) -> dict[str, Any]:
    require_language(conn, lang)
    return content.list_items(conn, lang, q=q, kind=kind, shelf=shelf, limit=limit, offset=offset)


@router.get("/recommend")
def recommend(
    lang: str = Query(..., min_length=2, max_length=8),
    n: int = Query(12, ge=1, le=50),
    conn: Connection = Depends(get_conn),
) -> dict[str, Any]:
    require_language(conn, lang)
    return up_next(conn, lang, n)


@router.post("/content/upload", status_code=201)
async def upload(
    lang: str = Form(..., min_length=2, max_length=8),
    file: UploadFile = File(...),
    conn: Connection = Depends(get_conn),
    cfg: AppConfig = Depends(get_cfg),
) -> dict[str, Any]:
    require_language(conn, lang)
    data = await file.read(UPLOAD_LIMIT + 1)
    if len(data) > UPLOAD_LIMIT:
        raise HTTPException(status_code=413, detail="Files up to 80 MB are supported.")
    name = file.filename or "upload"
    suffix = name.lower().rsplit(".", 1)[-1] if "." in name else ""
    if suffix not in {"epub", "pdf", "txt"}:
        raise HTTPException(status_code=422, detail="Upload an .epub, .pdf or .txt file.")
    path = reading.store_upload(cfg, lang, name, data)
    try:
        if suffix == "epub":
            doc = documents.parse_epub(path)
        elif suffix == "pdf":
            doc = documents.parse_pdf(path)
        else:
            doc = documents.parse_text(name.rsplit(".", 1)[0], data.decode("utf-8", errors="replace"))
    except documents.DocumentError as exc:
        path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    item_id, analysed = reading.import_document(
        conn, cfg, lang, doc, item_type="text" if suffix == "txt" else suffix, source="upload", local_path=path
    )
    return {**content.get_item(conn, item_id), "analysing_in_background": not analysed}


@router.post("/content/article", status_code=201)
def add_article(body: AddArticle, conn: Connection = Depends(get_conn), cfg: AppConfig = Depends(get_cfg)) -> dict[str, Any]:
    require_language(conn, body.lang)
    try:
        doc = documents.fetch_article(body.url)
    except documents.DocumentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    item_id, analysed = reading.import_document(conn, cfg, body.lang, doc, item_type="article", source="web", source_url=body.url)
    return {**content.get_item(conn, item_id), "analysing_in_background": not analysed}


@router.post("/content/text", status_code=201)
def add_text(body: AddText, conn: Connection = Depends(get_conn), cfg: AppConfig = Depends(get_cfg)) -> dict[str, Any]:
    require_language(conn, body.lang)
    try:
        doc = documents.parse_text(body.title, body.text)
    except documents.DocumentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    item_id, analysed = reading.import_document(conn, cfg, body.lang, doc, item_type="text", source="paste")
    return {**content.get_item(conn, item_id), "analysing_in_background": not analysed}


@router.post("/content/youtube", status_code=201)
def add_youtube(body: AddYouTube, conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    require_language(conn, body.lang)
    video_id = parse_video_id(body.url)
    if not video_id:
        raise HTTPException(status_code=422, detail="That doesn't look like a YouTube link.")
    try:
        info = fetch_info(video_id)
    except YouTubeError as exc:
        raise HTTPException(status_code=502, detail=f"YouTube: {exc}") from exc
    item_id = content.upsert_youtube(
        conn, body.lang, video_id, title=info.title, channel=info.channel, duration=info.duration
    )
    content.mark_opened(conn, item_id)
    if not content.cues_of(conn, item_id):
        try:
            captions = fetch_captions(video_id, body.lang, info)
        except YouTubeError:
            captions = None
        if captions:
            content.save_transcript(conn, item_id, body.lang, captions.kind, captions.fmt, captions.cues)
            content.set_metadata(conn, item_id, captions=captions.kind, caption_track=captions.track_lang)
            content.analyze_item(conn, item_id)
        else:
            content.set_metadata(conn, item_id, captions="none")
    return content.get_item(conn, item_id)


@router.post("/content/scan")
def scan(conn: Connection = Depends(get_conn), cfg: AppConfig = Depends(get_cfg)) -> dict[str, Any]:
    return content.scan_media(conn, cfg)


@router.get("/content/evidence")
def evidence(
    lang: str = Query(..., min_length=2, max_length=8), conn: Connection = Depends(get_conn)
) -> dict[str, Any]:
    require_language(conn, lang)
    return {**content_evidence(conn, lang), "job": latest_job(conn, "fetch_history_captions")}


@router.post("/content/history/fetch", status_code=202)
def fetch_history(body: HistoryRequest, conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    job_id = enqueue(conn, "fetch_history_captions", body.model_dump(exclude_none=True))
    return {"job_id": job_id}


@router.get("/jobs/{job_id}")
def job(job_id: int, conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    found = get_job(conn, job_id)
    if not found:
        raise HTTPException(status_code=404, detail="no such job")
    return found


@router.get("/content/{item_id}")
def get_item(item_id: int, conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    try:
        item = content.get_item(conn, item_id)
    except content.ContentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    content.mark_opened(conn, item_id)
    return item


@router.post("/content/{item_id}/captions")
def refetch_captions(item_id: int, conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    try:
        item = content.get_item(conn, item_id)
    except content.ContentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if item["source"] != "youtube":
        raise HTTPException(status_code=422, detail="Captions can only be fetched for YouTube videos.")
    try:
        captions = fetch_captions(item["external_id"], item["language"])
    except YouTubeError as exc:
        raise HTTPException(status_code=502, detail=f"YouTube: {exc}") from exc
    if not captions:
        content.set_metadata(conn, item_id, captions="none")
        raise HTTPException(status_code=404, detail="This video has no captions in this language.")
    content.save_transcript(conn, item_id, item["language"], captions.kind, captions.fmt, captions.cues)
    content.set_metadata(conn, item_id, captions=captions.kind, caption_track=captions.track_lang)
    content.analyze_item(conn, item_id)
    return content.get_item(conn, item_id)


@router.get("/content/{item_id}/transcript")
def transcript(item_id: int, conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    try:
        return content.annotated_transcript(conn, item_id)
    except content.ContentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/content/{item_id}/pages")
def page_list(item_id: int, conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    entries = reading.pages(conn, item_id)
    return {"total": len(entries), "pages": [{"n": p["n"], "title": p["title"]} for p in entries]}


@router.get("/content/{item_id}/page/{number}")
def read_page(item_id: int, number: int, conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    try:
        return reading.page(conn, item_id, number)
    except content.ContentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/content/{item_id}/read-progress")
def read_progress(item_id: int, body: PageProgress, conn: Connection = Depends(get_conn)) -> dict[str, bool]:
    reading.record_page_progress(conn, item_id, body.page, body.total)
    return {"ok": True}


@router.post("/content/{item_id}/dismiss")
def dismiss(item_id: int, conn: Connection = Depends(get_conn)) -> dict[str, bool]:
    conn.execute(text("UPDATE content_items SET status = 'dismissed' WHERE id = :id"), {"id": item_id})
    return {"ok": True}


@router.get("/content/{item_id}/media")
def media(item_id: int, request: Request, conn: Connection = Depends(get_conn), cfg: AppConfig = Depends(get_cfg)) -> FileResponse:
    try:
        path = content.media_path(cfg, content.get_item(conn, item_id))
    except content.ContentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path)  # Starlette serves HTTP Range requests, so seeking works
