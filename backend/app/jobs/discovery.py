"""Background jobs for Phase 8: content discovery and the weekly review."""

from __future__ import annotations

from typing import Any

from app.jobs.runner import JobContext, register
from app.services.discover import update_content


@register("update_content")
def update_content_job(ctx: JobContext) -> dict[str, Any]:
    ctx.progress(0.02, "looking for new content")
    return update_content(
        ctx.engine, ctx.cfg, ctx.payload.get("lang"), per_run=ctx.payload.get("per_run"),
        progress=lambda message: ctx.progress(0.5, message),
    )


@register("evolve_profile")
def evolve_profile_job(ctx: JobContext) -> dict[str, Any]:
    from app.ai.config import load_ai_config
    from app.ai.gateway import Gateway
    from app.services.evolve import evolve

    ctx.progress(0.05, "measuring the week")
    gateway = Gateway(load_ai_config(ctx.cfg.root), ctx.engine)
    return evolve(ctx.engine, ctx.cfg, gateway, days=int(ctx.payload.get("days", 7)), use_llm=not ctx.payload.get("no_llm"))
