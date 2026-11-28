from __future__ import annotations

import json
import threading
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import OperationalError

from app.config import AppConfig
from app.timeutil import to_iso, utc_now


@dataclass
class JobContext:
    engine: Engine
    cfg: AppConfig
    job_id: int | None
    payload: dict[str, Any]
    on_progress: Callable[[float, str], None] | None = None

    def progress(self, fraction: float, message: str = "") -> None:
        if self.on_progress:
            self.on_progress(fraction, message)
        if self.job_id is None:
            return
        try:
            with self.engine.begin() as conn:
                conn.execute(
                    text("UPDATE jobs SET progress = :p, result_json = :r WHERE id = :id"),
                    {"p": round(max(0.0, min(1.0, fraction)), 4), "r": json.dumps({"message": message}), "id": self.job_id},
                )
        except OperationalError:
            pass  # the database is busy with the job's own work: the next progress report will get through

    def cancelled(self) -> bool:
        if self.job_id is None:
            return False
        with self.engine.begin() as conn:
            return conn.execute(text("SELECT status FROM jobs WHERE id = :id"), {"id": self.job_id}).scalar() == "cancelled"


Handler = Callable[[JobContext], dict[str, Any]]
HANDLERS: dict[str, Handler] = {}


def register(kind: str) -> Callable[[Handler], Handler]:
    def wrap(fn: Handler) -> Handler:
        HANDLERS[kind] = fn
        return fn

    return wrap


# Each lane has its own worker thread, so slow work of one sort never holds up another: fetching new content waits for
# the network, not for Whisper transcribing a podcast or a whole language being re-scored.
LANES = ("cpu", "net", "gpu")
DEFAULT_LANE = {
    "update_content": "net",
    "verify_candidates": "net",
    "fetch_history_captions": "net",
    "transcribe": "gpu",
    "ocr_manga": "gpu",
}


def enqueue(conn: Connection, kind: str, payload: dict[str, Any], lane: str | None = None, dedupe: bool = True) -> int:
    lane = lane or DEFAULT_LANE.get(kind, "cpu")
    if dedupe:
        existing = conn.execute(
            text("SELECT id FROM jobs WHERE kind = :k AND status IN ('queued', 'running') ORDER BY id LIMIT 1"), {"k": kind}
        ).scalar()
        if existing:
            return existing  # one job of a kind at a time
    return conn.execute(
        text("INSERT INTO jobs (kind, lane, payload_json) VALUES (:k, :lane, :p)"),
        {"k": kind, "lane": lane, "p": json.dumps(payload)},
    ).lastrowid


def get_job(conn: Connection, job_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        text("SELECT id, kind, status, progress, result_json, error, created_at, started_at, finished_at FROM jobs WHERE id = :id"),
        {"id": job_id},
    ).first()
    if not row:
        return None
    job = dict(zip(("id", "kind", "status", "progress", "result", "error", "created_at", "started_at", "finished_at"), row))
    job["result"] = json.loads(job["result"]) if job["result"] else None
    return job


def latest_job(conn: Connection, kind: str) -> dict[str, Any] | None:
    job_id = conn.execute(text("SELECT id FROM jobs WHERE kind = :k ORDER BY id DESC LIMIT 1"), {"k": kind}).scalar()
    return get_job(conn, job_id) if job_id else None


class Runner(threading.Thread):
    """The worker for one lane of the jobs table (LANES)."""

    def __init__(self, engine: Engine, cfg: AppConfig, poll_seconds: float = 1.0, lane: str = "cpu") -> None:
        super().__init__(name=f"lingo-jobs-{lane}", daemon=True)
        self.engine, self.cfg, self.poll, self.lane = engine, cfg, poll_seconds, lane
        self.stopping = threading.Event()

    def run(self) -> None:
        with self.engine.begin() as conn:  # this lane's jobs left 'running' by a crash start over
            conn.execute(text("UPDATE jobs SET status = 'queued' WHERE status = 'running' AND lane = :lane"), {"lane": self.lane})
        while not self.stopping.is_set():
            job = self._claim()
            if job is None:
                self.stopping.wait(self.poll)
                continue
            self._run(*job)

    def _claim(self) -> tuple[int, str, dict[str, Any]] | None:
        with self.engine.begin() as conn:
            row = conn.execute(
                text(
                    "UPDATE jobs SET status = 'running', started_at = :now, attempts = attempts + 1 WHERE id = "
                    "(SELECT id FROM jobs WHERE status = 'queued' AND lane = :lane ORDER BY priority, id LIMIT 1) "
                    "RETURNING id, kind, payload_json"
                ),
                {"now": to_iso(utc_now()), "lane": self.lane},
            ).first()
        return (row[0], row[1], json.loads(row[2] or "{}")) if row else None

    def _run(self, job_id: int, kind: str, payload: dict[str, Any]) -> None:
        handler = HANDLERS.get(kind)
        try:
            if handler is None:
                raise RuntimeError(f"no handler for job kind '{kind}'")
            result = handler(JobContext(self.engine, self.cfg, job_id, payload))
            status, error = "done", None
        except Exception as exc:  # a failed job must not kill the worker
            result, status, error = None, "failed", f"{exc}\n{traceback.format_exc(limit=3)}"[:2000]
        with self.engine.begin() as conn:
            current = conn.execute(text("SELECT status FROM jobs WHERE id = :id"), {"id": job_id}).scalar()
            conn.execute(
                text("UPDATE jobs SET status = :s, progress = 1, result_json = :r, error = :e, finished_at = :now WHERE id = :id"),
                {
                    "s": "cancelled" if current == "cancelled" else status,
                    "r": json.dumps(result) if result is not None else None,
                    "e": error,
                    "now": to_iso(utc_now()),
                    "id": job_id,
                },
            )

    def stop(self) -> None:
        self.stopping.set()


def start_runners(engine: Engine, cfg: AppConfig) -> list[Runner]:
    runners = [Runner(engine, cfg, lane=lane) for lane in LANES]
    for runner in runners:
        runner.start()
    return runners
