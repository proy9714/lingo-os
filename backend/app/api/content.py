from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import Connection, text

from app.api.deps import get_cfg, get_conn, get_dict_conn, require_language
from app.config import AppConfig
from app.engine.evidence import content_evidence
from app.ingest import documents
from app.ingest.youtube import YouTubeError, fetch_captions, fetch_info, parse_video_id
from app.jobs import analysis, history, transcribe  # noqa: F401 - registers the job handlers
from app.jobs.runner import enqueue, get_job, latest_job
from app.services import calibration, content, reading, taste
from app.services import recommend as ranking
from app.services.recommend import feed, up_next
from app.timeutil import to_iso, utc_now

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
    shelf: str = Query("watch", pattern="^(watch|listen|read|manga)$"),
    state: str = Query("all", pattern="^(all|watched|mine|later)$"),
    limit: int = Query(60, ge=1, le=300),
    offset: int = Query(0, ge=0),
    conn: Connection = Depends(get_conn),
) -> dict[str, Any]:
    """The library. `state`: watched = videos you've watched; mine = what you added or opened (not untouched
    suggestions); later = saved to watch, read or listen to later."""
    require_language(conn, lang)
    return content.list_items(conn, lang, q=q, kind=kind, shelf=shelf, state=state, limit=limit, offset=offset)


@router.get("/feed")
def suggestions(
    lang: str = Query(..., min_length=2, max_length=8),
    shelf: str = Query("watch", pattern="^(watch|listen|read)$"),
    offset: int = Query(0, ge=0),
    limit: int = Query(24, ge=1, le=60),
    level: str | None = Query(None, pattern="^(easy|right|hard)$"),
    conn: Connection = Depends(get_conn),
) -> dict[str, Any]:
    """Suggestions for one shelf, best first, paged for infinite scrolling. Never anything you've watched or finished."""
    require_language(conn, lang)
    return feed(conn, lang, shelf, offset, limit, level)


@router.get("/recommend")
def recommend(
    lang: str = Query(..., min_length=2, max_length=8),
    n: int = Query(12, ge=1, le=50),
    conn: Connection = Depends(get_conn),
) -> dict[str, Any]:
    require_language(conn, lang)
    return up_next(conn, lang, n)


class SeenRequest(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=200)


@router.post("/recommend/seen")
def seen(body: SeenRequest, conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    """Suggestion cards that were on screen: ones you keep passing by without opening slowly sink."""
    from app.services import ranker

    return {"counted": ranker.record_seen(conn, body.ids)}


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


@router.post("/content/{item_id}/transcribe", status_code=202)
def start_transcription(item_id: int, conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    """Make a transcript with Whisper on this laptop (videos without captions in the language, your own media)."""
    from app.db import settings_store
    from app.ingest import whisper

    try:
        item = content.get_item(conn, item_id)
    except content.ContentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if settings_store.get(conn, whisper.SETTING) not in whisper.MODELS:
        raise HTTPException(status_code=409, detail="Transcription is off: choose a model in Settings → Transcription.")
    if item["type"] not in content.WATCH_TYPES:
        raise HTTPException(status_code=422, detail="Only videos and audio can be transcribed.")
    running = conn.execute(
        text("SELECT id FROM jobs WHERE kind = 'transcribe' AND status IN ('queued', 'running') "
             "AND json_extract(payload_json, '$.item_id') = :i ORDER BY id DESC LIMIT 1"),
        {"i": item_id},
    ).scalar()
    if running:
        return {"job_id": running}
    return {"job_id": enqueue(conn, "transcribe", {"item_id": item_id}, lane="gpu", dedupe=False)}


@router.get("/whisper")
def whisper_settings(conn: Connection = Depends(get_conn), cfg: AppConfig = Depends(get_cfg)) -> dict[str, Any]:
    from app.db import settings_store
    from app.ingest import whisper

    chosen = settings_store.get(conn, whisper.SETTING)
    return {
        "model": chosen if chosen in whisper.MODELS else None,
        "models": [{"id": k, **v, "downloaded": whisper.model_ready(cfg, k)} for k, v in whisper.MODELS.items()],
    }


class WhisperChoice(BaseModel):
    model: str | None = Field(default=None, pattern="^(base|small)$")


@router.put("/whisper")
def choose_whisper(body: WhisperChoice, conn: Connection = Depends(get_conn), cfg: AppConfig = Depends(get_cfg)) -> dict[str, Any]:
    from app.db import settings_store
    from app.ingest import whisper

    settings_store.put(conn, whisper.SETTING, body.model)
    return whisper_settings(conn, cfg)


@router.get("/content/{item_id}/transcript")
def transcript(item_id: int, conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    try:
        return content.annotated_transcript(conn, item_id)
    except content.ContentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/content/{item_id}/translation")
def translation(request: Request, item_id: int, to: str = Query("en", pattern="^en$"), conn: Connection = Depends(get_conn),
                cfg: AppConfig = Depends(get_cfg)) -> dict[str, Any]:
    """English (or another language's) captions to show under the transcript; cached once fetched."""
    import json as _json

    from app.ai.gateway import AIUnavailable
    from app.ingest.youtube import fetch_translation
    from app.services.explain import translate_with_ai

    try:
        item = content.get_item(conn, item_id)
    except content.ContentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if item["source"] != "youtube" or not item["external_id"]:
        return {"to": to, "available": False, "cues": [], "reason": "Translations come with YouTube videos only."}
    cache = cfg.data_dir / "cache" / "translations" / f"{item['external_id']}.{to}.json"
    if cache.exists():
        return _json.loads(cache.read_text(encoding="utf-8"))
    source = "youtube"
    try:
        found = [{"start_ms": c.start_ms, "end_ms": c.end_ms, "text": c.text} for c in fetch_translation(item["external_id"], to)]
    except YouTubeError:
        found = []  # YouTube refuses its automatic translations to programs more often than not
    reason = None
    if not found:
        try:
            found, source = translate_with_ai(request.app.state.ai, conn, item_id, item["language"]), "ai"
        except AIUnavailable as exc:
            reason = f"No English captions on YouTube, and AI translation is off ({exc})."
    body = {"to": to, "available": bool(found), "source": source if found else None, "cues": found, "reason": reason}
    if not found:
        return body  # not cached: an AI key added later can still translate it
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(_json.dumps(body, ensure_ascii=False), encoding="utf-8")
    return body


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
    """Not interested: never suggested again, and the taste model learns from it."""
    lang = conn.execute(text("SELECT language_code FROM content_items WHERE id = :id"), {"id": item_id}).scalar()
    conn.execute(text("UPDATE content_items SET status = 'dismissed' WHERE id = :id"), {"id": item_id})
    if lang:
        content.set_metadata(conn, item_id, dismissed_by_you=1, dismissed_at=to_iso(utc_now()))
        taste.invalidate(lang)
        ranking.invalidate()
    return {"ok": True}


class Watched(BaseModel):
    watched: bool = True


@router.post("/content/{item_id}/watched")
def mark_watched(item_id: int, body: Watched, conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    """Already watched / completed: the item leaves the suggestions and shows under Watched. `watched: false` undoes it."""
    try:
        item = content.set_watched(conn, item_id, body.watched)
    except content.ContentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    taste.invalidate(item["language"])
    ranking.invalidate()
    return item


class Later(BaseModel):
    later: bool = True


@router.post("/content/{item_id}/later")
def save_for_later(item_id: int, body: Later, conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    """Watch later / read later / listen later (`later: false` takes it off the list)."""
    try:
        item = content.set_later(conn, item_id, body.later)
    except content.ContentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    ranking.invalidate()
    return item


class Difficulty(BaseModel):
    value: int | None = Field(default=None, ge=1, le=5)


@router.put("/content/{item_id}/difficulty")
def rate_difficulty(item_id: int, body: Difficulty, conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    """Very easy (1) … very hard (5): moves your "just right" level for videos or reading. null clears it."""
    try:
        result = calibration.rate(conn, item_id, body.value)
    except content.ContentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    ranking.invalidate()
    return result


@router.get("/taste")
def taste_summary(
    lang: str = Query(..., min_length=2, max_length=8),
    conn: Connection = Depends(get_conn),
    dict_conn: Connection = Depends(get_dict_conn),
) -> dict[str, Any]:
    """What the app has learned: channels and topics you like, lengths you finish, your calibrated level window."""
    from app.dictionary.lookup import lookup

    require_language(conn, lang)
    summary = taste.explain(conn, lang)
    # show only real words as topics (a presenter's name isn't a topic); an empty dictionary leaves them all
    has_dictionary = bool(dict_conn.execute(text("SELECT 1 FROM dict_terms LIMIT 1")).first())
    if has_dictionary:
        def is_word(w: str) -> bool:
            entries = lookup(dict_conn, lang, [w], limit=3)["entries"]
            return any("name" not in (e.get("pos") or []) for e in entries)

        summary["topics"] = [w for w in summary["topics"] if is_word(w)]
    return {**summary, "calibration": calibration.summary(conn, lang)}


@router.get("/content/{item_id}/media", response_model=None)
def media(item_id: int, request: Request, conn: Connection = Depends(get_conn), cfg: AppConfig = Depends(get_cfg)) -> FileResponse | RedirectResponse:
    """Play or download a recording: your own files, and podcast episodes (from here once downloaded, otherwise
    straight from the publisher; ?download=1 fetches the episode here first, for a device saving it offline)."""
    try:
        item = content.get_item(conn, item_id)
        if item["type"] == "podcast_episode":
            from app.services import podcasts

            path = podcasts.local_audio(cfg, conn, item)
            if path is None and request.query_params.get("download"):
                path = podcasts.ensure_local_audio(conn, cfg, item_id)
            if path is None:
                url = (item.get("metadata") or {}).get("enclosure_url")
                if not url:
                    raise content.ContentError("this episode has no audio file")
                return RedirectResponse(url, status_code=302)
            return FileResponse(path)
        path = content.media_path(cfg, item)
    except content.ContentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - a publisher that won't hand over the file
        from app.services.podcasts import PodcastError

        if isinstance(exc, PodcastError):
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        raise
    return FileResponse(path)  # Starlette serves HTTP Range requests, so seeking works
