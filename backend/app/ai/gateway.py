"""The one door to every model. Feature code calls `gateway.structured(task, prompt, variables, Schema)`.

- Routing: config/llm.yaml maps a task to a provider and model, with fallbacks. `local_only` keeps everything local.
- Cache: identical (task, model, prompt version, input) requests are answered from `ai_cache`.
- Log: every call lands in `ai_calls` (latency, tokens, estimated cost when prices are configured).
- Output: JSON validated against a Pydantic model, with one repair retry.
- Without a key the gateway reports *why* it is off, and features fall back to dictionary-only.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, replace
from pathlib import Path
from string import Template
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError
from sqlalchemy import Engine, text

from app.ai.config import AIConfig, ProviderConfig, TaskRoute
from app.ai.providers import LLMRequest, LLMResponse, ProviderError, make_provider
from app.db import settings_store

CHOICE_KEY = "ai.choice"  # app_settings: {"provider": "auto" | name, "models": {name: {tier: model}}}
TIERS = ("fast", "smart")

PROMPTS = Path(__file__).parent / "prompts"
T = TypeVar("T", bound=BaseModel)


class AIUnavailable(Exception):
    """No provider can serve this task right now. The message says why, in plain words."""


@dataclass(frozen=True)
class Prompt:
    name: str
    version: int
    system: str
    user: str


def load_prompt(name: str) -> Prompt:
    """Prompt files: a `version: N` line, then `=== system` and `=== user` sections using $variables."""
    raw = (PROMPTS / f"{name}.md").read_text(encoding="utf-8")
    match = re.match(r"version:\s*(\d+)\s*\n", raw)
    if not match:
        raise ValueError(f"prompt {name} needs a 'version: N' first line")
    sections = dict(re.findall(r"^=== (system|user)\s*\n(.*?)(?=^=== |\Z)", raw, flags=re.S | re.M))
    return Prompt(name, int(match.group(1)), sections.get("system", "").strip(), sections.get("user", "").strip())


def json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Pydantic's schema with $refs inlined and titles dropped: the subset every provider accepts."""
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(defs[node["$ref"].split("/")[-1]])
            return {k: walk(v) for k, v in node.items() if k != "title"}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(schema)


def parse_json(raw: str) -> Any:
    cleaned = raw.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", cleaned, flags=re.S)
    if fence:
        cleaned = fence.group(1)
    if not cleaned.startswith(("{", "[")):
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            cleaned = cleaned[start : end + 1]
    return json.loads(cleaned)


class Gateway:
    def __init__(self, cfg: AIConfig, engine: Engine, transport: httpx.BaseTransport | None = None) -> None:
        self.cfg = cfg
        self.engine = engine
        self.providers = {name: make_provider(p, transport) for name, p in cfg.providers.items()}

    # ------------------------------------------------------------------ status

    def _usable(self, name: str) -> tuple[ProviderConfig | None, str | None]:
        provider = self.cfg.providers.get(name)
        if provider is None:
            return None, f"provider '{name}' is not configured in config/llm.yaml"
        if self.cfg.local_only and not provider.is_local:
            return None, f"local-only mode is on and '{name}' is a cloud provider"
        reason = provider.unavailable_reason()
        return (None, reason) if reason else (provider, None)

    def choice(self) -> dict[str, Any]:
        """Which provider the learner picked in Settings ('auto' = the first with a key) and any models they chose."""
        try:
            with self.engine.connect() as conn:
                saved = settings_store.get(conn, CHOICE_KEY, {}) or {}
        except Exception:  # noqa: BLE001 - no settings table (a bare test database): use the defaults
            saved = {}
        provider = saved.get("provider") if saved.get("provider") in self.cfg.choosable else "auto"
        return {"provider": provider, "models": saved.get("models") or {}}

    def set_choice(self, provider: str | None = None, models: dict[str, dict[str, str | None]] | None = None) -> dict[str, Any]:
        current = self.choice()
        if provider is not None:
            if provider != "auto" and provider not in self.cfg.choosable:
                raise ValueError(f"unknown provider '{provider}'")
            current["provider"] = provider
        for name, tiers in (models or {}).items():
            if name not in self.cfg.choosable:
                raise ValueError(f"unknown provider '{name}'")
            own = dict(current["models"].get(name) or {})
            for tier, model in tiers.items():
                if tier not in TIERS:
                    raise ValueError(f"unknown tier '{tier}'")
                if model:
                    own[tier] = str(model)[:120]
                else:
                    own.pop(tier, None)  # back to the default
            current["models"][name] = own
        with self.engine.begin() as conn:
            settings_store.put(conn, CHOICE_KEY, current)
        return current

    def model_for(self, name: str, tier: str | None, choice: dict[str, Any] | None = None) -> str:
        provider = self.cfg.providers[name]
        chosen = ((choice or self.choice())["models"].get(name) or {}).get(tier or "") if tier else None
        return chosen or provider.model_for(tier) or ""

    def route(self, task: str) -> list[tuple[str, TaskRoute]]:
        """Usable providers for a task, primary first. Raises AIUnavailable with the reason if none."""
        route = self.cfg.tasks.get(task)
        if route is None:
            raise AIUnavailable(f"task '{task}' has no route in config/llm.yaml")
        chain, reasons = [], []
        if route.tier:
            # the provider chosen in Settings; 'auto' tries each choosable provider in order and uses the first with a key
            choice = self.choice()
            names = [choice["provider"]] if choice["provider"] != "auto" else self.cfg.choosable
            candidates = [(name, replace(route, model=self.model_for(name, route.tier, choice))) for name in names]
            candidates += [(name, route) for name in route.fallback if name not in names]
        else:
            candidates = [(name, route) for name in (route.use, *route.fallback)]
        for name, own in candidates:
            provider, reason = self._usable(name)
            if provider:
                chain.append((name, own))
            elif reason:
                reasons.append(reason)
        if not chain:
            raise AIUnavailable("; ".join(dict.fromkeys(reasons)) or "no provider available")
        return chain

    def status(self, task: str = "lookup.context_gloss") -> dict[str, Any]:
        try:
            chain = self.route(task)
        except AIUnavailable as exc:
            return {"enabled": False, "reason": str(exc), "local_only": self.cfg.local_only}
        name, route = chain[0]
        provider = self.cfg.providers[name]
        return {
            "enabled": True,
            "provider": provider.label or name,
            "provider_id": name,
            "kind": provider.kind,
            "model": route.model or provider.default_model,
            "local_only": self.cfg.local_only,
        }

    # ------------------------------------------------------------------ calls

    def structured(
        self, task: str, prompt_name: str, variables: dict[str, Any], schema: type[T], *, cache: bool = True
    ) -> tuple[T, dict[str, Any]]:
        """Run a task and return (validated result, meta). Raises AIUnavailable when nothing can answer."""
        prompt = load_prompt(prompt_name)
        system = Template(prompt.system).substitute(variables)
        user = Template(prompt.user).substitute(variables)
        shape = json_schema(schema)
        errors: list[str] = []
        for name, route in self.route(task):
            provider_cfg = self.cfg.providers[name]
            model = route.model or provider_cfg.default_model or ""
            key = hashlib.sha256(
                json.dumps([task, name, model, prompt.name, prompt.version, variables], sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest()
            if cache and (hit := self._cache_get(key)) is not None:
                try:
                    return schema.model_validate(hit), {"provider": name, "model": model, "cached": True}
                except ValidationError:
                    pass  # schema changed since: ask again
            request = LLMRequest(system, user, model, route.temperature, shape, route.thinking, route.timeout)
            try:
                result, used_model = self._ask(task, name, provider_cfg, request, schema)
            except ProviderError as exc:
                errors.append(str(exc))
                continue
            if cache:
                self._cache_put(key, task, used_model, result.model_dump())
            return result, {"provider": name, "model": used_model, "cached": False}
        raise AIUnavailable("; ".join(errors) or "no provider answered")

    def chat(
        self, task: str, system: str, history: list[tuple[str, str]], message: str
    ) -> tuple[str, dict[str, Any]]:
        """Free-text, multi-turn reply (the tutor). Not cached: conversations don't repeat."""
        errors: list[str] = []
        for name, route in self.route(task):
            provider_cfg = self.cfg.providers[name]
            request = LLMRequest(
                system, message, route.model or provider_cfg.default_model or "", route.temperature, None, route.thinking,
                route.timeout, history,
            )
            provider = self.providers[name]
            started = time.perf_counter()
            try:
                try:
                    response = self._call(task, name, provider_cfg, provider, request)
                except ProviderError as exc:
                    if exc.model_missing and provider_cfg.default_model and provider_cfg.default_model != request.model:
                        request.model = provider_cfg.default_model
                        response = self._call(task, name, provider_cfg, provider, request)
                    else:
                        raise
            except ProviderError as exc:
                errors.append(str(exc))
                continue
            meta = {
                "provider": name, "model": request.model, "tokens_in": response.tokens_in, "tokens_out": response.tokens_out,
                "latency_ms": int((time.perf_counter() - started) * 1000),
            }
            return response.text.strip(), meta
        raise AIUnavailable("; ".join(errors) or "no provider answered")

    def _ask(
        self, task: str, name: str, provider_cfg: ProviderConfig, request: LLMRequest, schema: type[T]
    ) -> tuple[T, str]:
        provider = self.providers[name]
        try:
            response = self._call(task, name, provider_cfg, provider, request)
        except ProviderError as exc:
            if exc.model_missing and provider_cfg.default_model and provider_cfg.default_model != request.model:
                request.model = provider_cfg.default_model  # e.g. an alias that doesn't exist on this account
                response = self._call(task, name, provider_cfg, provider, request)
            else:
                raise
        try:
            return schema.model_validate(parse_json(response.text)), request.model
        except (ValueError, ValidationError) as exc:
            repair = LLMRequest(
                request.system,
                f"{request.prompt}\n\nYour previous reply could not be used ({str(exc)[:300]}). "
                "Reply again with only the JSON object, matching the requested fields exactly.",
                request.model,
                request.temperature,
                request.schema,
                request.thinking,
                request.timeout,
            )
            response = self._call(task, name, provider_cfg, provider, repair)
            try:
                return schema.model_validate(parse_json(response.text)), request.model
            except (ValueError, ValidationError) as again:
                raise ProviderError(f"{name} gave an unusable answer twice: {str(again)[:200]}") from again

    def _call(self, task: str, name: str, cfg: ProviderConfig, provider: Any, request: LLMRequest) -> LLMResponse:
        started = time.perf_counter()
        try:
            response = provider.complete(request)
        except ProviderError as exc:
            self._log(task, cfg, request.model, ok=False, started=started, error=str(exc))
            raise
        self._log(task, cfg, request.model, ok=True, started=started, response=response)
        return response

    # ------------------------------------------------------------------ storage

    def _cache_get(self, key: str) -> Any | None:
        with self.engine.begin() as conn:
            row = conn.execute(text("SELECT response_json FROM ai_cache WHERE key_hash = :k"), {"k": key}).first()
            if row:
                conn.execute(text("UPDATE ai_cache SET hits = hits + 1 WHERE key_hash = :k"), {"k": key})
                return json.loads(row[0])
        return None

    def _cache_put(self, key: str, task: str, model: str, value: Any) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO ai_cache (key_hash, task, model, response_json) VALUES (:k, :t, :m, :r) "
                    "ON CONFLICT(key_hash) DO UPDATE SET response_json = excluded.response_json"
                ),
                {"k": key, "t": task, "m": model, "r": json.dumps(value, ensure_ascii=False)},
            )

    def _log(
        self,
        task: str,
        cfg: ProviderConfig,
        model: str,
        *,
        ok: bool,
        started: float,
        response: LLMResponse | None = None,
        error: str | None = None,
    ) -> None:
        tokens_in = response.tokens_in if response else None
        tokens_out = response.tokens_out if response else None
        price = cfg.prices.get(model)
        cost = None
        if price and tokens_in is not None and tokens_out is not None:
            cost = round((tokens_in * price.get("in", 0) + tokens_out * price.get("out", 0)) / 1_000_000, 6)
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO ai_calls (task, kind, provider, model, ok, latency_ms, units_in, units_out, cost_estimate, error) "
                    "VALUES (:task, 'llm', :provider, :model, :ok, :ms, :tin, :tout, :cost, :err)"
                ),
                {
                    "task": task, "provider": cfg.name, "model": model, "ok": int(ok),
                    "ms": int((time.perf_counter() - started) * 1000), "tin": tokens_in, "tout": tokens_out,
                    "cost": cost, "err": error[:500] if error else None,
                },
            )

    def usage(self, days: int = 30) -> dict[str, Any]:
        with self.engine.begin() as conn:
            rows = conn.execute(
                text(
                    "SELECT task, COUNT(*), SUM(ok), SUM(COALESCE(units_in, 0)), SUM(COALESCE(units_out, 0)), SUM(cost_estimate), "
                    "AVG(latency_ms) FROM ai_calls WHERE created_at >= strftime('%Y-%m-%dT%H:%M:%fZ', 'now', :since) GROUP BY task"
                ),
                {"since": f"-{days} days"},
            ).all()
            cached = conn.execute(text("SELECT COALESCE(SUM(hits), 0) FROM ai_cache")).scalar_one()
        tasks = [
            {
                "task": r[0], "calls": r[1], "ok": r[2] or 0, "tokens_in": r[3] or 0, "tokens_out": r[4] or 0,
                "cost": round(r[5], 4) if r[5] is not None else None, "avg_ms": round(r[6] or 0),
            }
            for r in rows
        ]
        costs = [t["cost"] for t in tasks if t["cost"] is not None]
        return {
            "days": days,
            "tasks": tasks,
            "calls": sum(t["calls"] for t in tasks),
            "cost": round(sum(costs), 4) if costs else None,
            "cache_hits": int(cached),
        }
