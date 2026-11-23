"""OCR a manga volume with mokuro (optional: only when mokuro is installed)."""

from __future__ import annotations

from typing import Any

from app.jobs.runner import JobContext, register
from app.services.manga import run_ocr


@register("ocr_manga")
def ocr_manga(ctx: JobContext) -> dict[str, Any]:
    item_id = int(ctx.payload["item_id"])
    ctx.progress(0.05, "running mokuro (this can take a while)")
    with ctx.engine.begin() as conn:
        return run_ocr(conn, ctx.cfg, item_id)
