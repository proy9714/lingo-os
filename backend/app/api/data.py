"""Export all your data to one file, or restore it (Settings → Your data, or the first-run screen)."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from app.api.deps import get_cfg
from app.config import AppConfig
from app.services import backup

router = APIRouter(prefix="/api/data", tags=["data"])


@router.get("/export")
def export(cfg: AppConfig = Depends(get_cfg)) -> FileResponse:
    """The backup file, to save anywhere (it's also kept in data/backups until you delete it)."""
    path = backup.export(cfg)
    return FileResponse(path, media_type="application/zip", filename=path.name)


@router.post("/import")
def restore(request: Request, file: UploadFile = File(...), cfg: AppConfig = Depends(get_cfg)) -> dict[str, Any]:
    """Replace this computer's data with a backup's; the current data is saved in data/backups first."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "upload.lingo"
        with path.open("wb") as out:
            shutil.copyfileobj(file.file, out, length=1024 * 1024)
        try:
            return backup.restore(cfg, request.app.state.engine, path)
        except backup.BackupError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
