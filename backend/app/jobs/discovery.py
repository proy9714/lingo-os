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
        progress=lambda fraction, message: ctx.progress(fraction, message),
        videos=bool(ctx.payload.get("videos", True)), articles=bool(ctx.payload.get("articles", True)),
    )


@register("verify_candidates")
def verify_candidates_job(ctx: JobContext) -> dict[str, Any]:
    from app.services import catalog, recommend
    from app.services.discover import Fetchers, load_sources

    lang = ctx.payload["lang"]
    keep = load_sources(ctx.cfg)["defaults"]["keep_bands"]
    ctx.progress(0.02, "checking the best estimated videos")
    result = catalog.verify(
        ctx.engine, lang, Fetchers(), keep, limit=int(ctx.payload.get("limit", 12)),
        say=lambda fraction, message: ctx.progress(fraction, message),
    )
    recommend.invalidate()
    return result


@register("evolve_profile")
def evolve_profile_job(ctx: JobContext) -> dict[str, Any]:
    from app.ai.config import load_ai_config
    from app.ai.gateway import Gateway
    from app.services.evolve import evolve

    ctx.progress(0.05, "measuring the week")
    gateway = Gateway(load_ai_config(ctx.cfg.root), ctx.engine)
    return evolve(ctx.engine, ctx.cfg, gateway, days=int(ctx.payload.get("days", 7)), use_llm=not ctx.payload.get("no_llm"))
