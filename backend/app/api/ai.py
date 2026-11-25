"""AI endpoints. All of them degrade to a 503 with a plain reason when no provider is available."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import Connection

from app.ai import keys
from app.ai.gateway import TIERS, AIUnavailable, Gateway
from app.ai.providers import ProviderError
from app.api.deps import get_cfg, get_conn, get_dict_conn, require_language
from app.config import AppConfig
from app.services import explain

router = APIRouter(prefix="/api/ai", tags=["ai"])


def get_ai(request: Request) -> Gateway:
    return request.app.state.ai


class GlossRequest(BaseModel):
    lang: str = Field(min_length=2, max_length=8)
    sentence: str = Field(min_length=1, max_length=1000)
    surface: str = Field(min_length=1, max_length=100)
    lemma: str = Field(min_length=1, max_length=200)
    pos: str = Field(default="", max_length=16)
    reading: str = Field(default="", max_length=200)


class GrammarRequest(BaseModel):
    lang: str = Field(min_length=2, max_length=8)
    sentence: str = Field(min_length=1, max_length=1000)


class Ping(BaseModel):
    ok: bool
    word: str = ""


def _unavailable(exc: AIUnavailable) -> HTTPException:
    return HTTPException(status_code=503, detail=f"AI explanations are off: {exc}")


@router.get("/status")
def status(ai: Gateway = Depends(get_ai)) -> dict[str, Any]:
    return {"context": ai.status("lookup.context_gloss"), "grammar": ai.status("lookup.grammar")}


@router.get("/usage")
def usage(days: int = Query(30, ge=1, le=365), ai: Gateway = Depends(get_ai)) -> dict[str, Any]:
    return ai.usage(days)


@router.post("/test")
def test(ai: Gateway = Depends(get_ai)) -> dict[str, Any]:
    """One tiny uncached call to check the key and model work."""
    try:
        result, meta = ai.structured("lookup.context_gloss", "ping", {"word": "Hallo"}, Ping, cache=False)
    except AIUnavailable as exc:
        raise _unavailable(exc) from exc
    return {"ok": result.ok, **meta}


@router.post("/gloss")
def gloss(
    body: GlossRequest,
    conn: Connection = Depends(get_conn),
    dict_conn: Connection = Depends(get_dict_conn),
    ai: Gateway = Depends(get_ai),
) -> dict[str, Any]:
    require_language(conn, body.lang)
    try:
        return explain.context_gloss(
            ai, conn, dict_conn, lang=body.lang, sentence=body.sentence, surface=body.surface, lemma=body.lemma,
            pos=body.pos, reading=body.reading,
        )
    except AIUnavailable as exc:
        raise _unavailable(exc) from exc


@router.post("/grammar")
def grammar(body: GrammarRequest, conn: Connection = Depends(get_conn), ai: Gateway = Depends(get_ai)) -> dict[str, Any]:
    require_language(conn, body.lang)
    try:
        return explain.grammar_breakdown(ai, conn, lang=body.lang, sentence=body.sentence)
    except AIUnavailable as exc:
        raise _unavailable(exc) from exc


# ------------------------------------------------------------------ choosing a provider


class ChoiceRequest(BaseModel):
    provider: str | None = Field(default=None, max_length=40)  # "auto" or a provider id
    models: dict[str, dict[str, str | None]] | None = None  # {provider: {"fast"|"smart": model or null for the default}}


class KeyRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=40)
    key: str = Field(default="", max_length=400)  # empty removes the key


def _providers(ai: Gateway) -> dict[str, Any]:
    choice = ai.choice()
    out = []
    for name in ai.cfg.choosable:
        provider = ai.cfg.providers[name]
        key = provider.api_key or ""
        out.append(
            {
                "id": name, "label": provider.label, "kind": provider.kind, "key_env": provider.api_key_env,
                "key_url": provider.key_url, "has_key": bool(key), "key_hint": f"…{key[-4:]}" if len(key) >= 12 else None,
                "defaults": {tier: provider.model_for(tier) for tier in TIERS},
                "models": {tier: ai.model_for(name, tier, choice) for tier in TIERS},
                "chosen": choice["models"].get(name) or {},
            }
        )
    status = ai.status("lookup.context_gloss")
    return {"selected": choice["provider"], "active": status.get("provider_id"), "local_only": ai.cfg.local_only, "providers": out}


@router.get("/providers")
def providers(ai: Gateway = Depends(get_ai)) -> dict[str, Any]:
    """Gemini, Claude, ChatGPT: which have a key, which one is used, and with which models. Keys are never sent back."""
    return _providers(ai)


@router.put("/choice")
def choose(body: ChoiceRequest, ai: Gateway = Depends(get_ai)) -> dict[str, Any]:
    try:
        ai.set_choice(body.provider, body.models)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _providers(ai)


@router.put("/keys")
def save_key(body: KeyRequest, ai: Gateway = Depends(get_ai), cfg: AppConfig = Depends(get_cfg)) -> dict[str, Any]:
    """Save (or remove) a provider's API key in .env on this computer; it works at once, without a restart."""
    provider = ai.cfg.providers.get(body.provider)
    if provider is None or not provider.label or not provider.api_key_env:
        raise HTTPException(status_code=422, detail=f"unknown provider '{body.provider}'")
    key = body.key.strip()
    if key and (len(key) < 12 or any(c.isspace() or not c.isprintable() for c in key)):
        raise HTTPException(status_code=422, detail="That doesn't look like an API key: paste it again without spaces.")
    keys.save(cfg.root / ".env", provider.api_key_env, key)
    return _providers(ai)


@router.get("/models")
def models(provider: str = Query(min_length=1, max_length=40), ai: Gateway = Depends(get_ai)) -> dict[str, Any]:
    """The models this key can use, to pick from in Settings."""
    adapter = ai.providers.get(provider)
    if provider not in ai.cfg.choosable or adapter is None:
        raise HTTPException(status_code=422, detail=f"unknown provider '{provider}'")
    reason = ai.cfg.providers[provider].unavailable_reason()
    if reason:
        raise HTTPException(status_code=409, detail=reason)
    try:
        return {"provider": provider, "models": adapter.list_models()}
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
