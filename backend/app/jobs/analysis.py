"""Analyse a large item (a whole book) off the request path."""

from __future__ import annotations

from typing import Any

from app.jobs.runner import JobContext, register
from app.services.content import analyze_item


@register("analyze_content")
def analyze_content(ctx: JobContext) -> dict[str, Any]:
    item_id = int(ctx.payload["item_id"])
    ctx.progress(0.1, "analysing text")
    with ctx.engine.begin() as conn:
        result = analyze_item(conn, item_id)
    return {"item_id": item_id, "analysed": result is not None}
