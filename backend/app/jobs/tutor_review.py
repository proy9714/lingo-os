"""After a tutor conversation: extract corrections, grammar points and a summary."""

from __future__ import annotations

from typing import Any

from app.ai.config import load_ai_config
from app.ai.gateway import Gateway
from app.jobs.runner import JobContext, register
from app.services.tutor import postprocess


@register("tutor_postprocess")
def tutor_postprocess(ctx: JobContext) -> dict[str, Any]:
    ctx.progress(0.1, "reviewing the conversation")
    gateway = Gateway(load_ai_config(ctx.cfg.root), ctx.engine)
    return postprocess(gateway, ctx.engine, int(ctx.payload["session_id"]))
