"""Read config/llm.yaml: providers, task routing and the local-only switch."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

LOCAL_KINDS = {"ollama"}


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    kind: str  # gemini | openai_compatible | ollama | fake
    api_key_env: str | None = None
    base_url: str | None = None
    default_model: str | None = None  # used when a task's model doesn't exist on this provider
    prices: dict[str, dict[str, float]] = field(default_factory=dict)  # model -> {in, out} USD per million tokens

    @property
    def api_key(self) -> str | None:
        return os.environ.get(self.api_key_env) if self.api_key_env else None

    @property
    def is_local(self) -> bool:
        if self.kind in LOCAL_KINDS or self.kind == "fake":
            return True
        url = self.base_url or ""
        return any(host in url for host in ("://localhost", "://127.0.0.1", "://[::1]"))

    def unavailable_reason(self) -> str | None:
        if self.kind == "gemini" and not self.api_key:
            return f"no {self.api_key_env or 'GEMINI_API_KEY'} in .env"
        if self.kind == "openai_compatible" and not self.base_url:
            return "no base_url configured"
        if self.kind == "openai_compatible" and self.api_key_env and not self.api_key and not self.is_local:
            return f"no {self.api_key_env} in .env"
        return None


@dataclass(frozen=True)
class TaskRoute:
    task: str
    use: str
    model: str
    temperature: float | None = None
    fallback: tuple[str, ...] = ()
    thinking: str | None = None  # 'off' asks the model to answer without thinking first (faster)
    timeout: float = 40.0


@dataclass(frozen=True)
class AIConfig:
    providers: dict[str, ProviderConfig]
    tasks: dict[str, TaskRoute]
    local_only: bool = False


def load_ai_config(root: Path) -> AIConfig:
    path = root / "config" / "llm.yaml"
    raw: dict[str, Any] = {}
    if path.exists():
        with path.open(encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
    return parse_ai_config(raw)


def parse_ai_config(raw: dict[str, Any]) -> AIConfig:
    providers = {
        name: ProviderConfig(
            name=name,
            kind=str(spec.get("kind", "gemini")),
            api_key_env=spec.get("api_key_env"),
            base_url=spec.get("base_url"),
            default_model=spec.get("default_model"),
            prices=spec.get("prices") or {},
        )
        for name, spec in (raw.get("providers") or {}).items()
    }
    tasks = {}
    for task, spec in (raw.get("tasks") or {}).items():
        fallback = spec.get("fallback") or []
        tasks[task] = TaskRoute(
            task=task,
            use=str(spec.get("use", "cloud")),
            model=str(spec.get("model", "")),
            temperature=spec.get("temperature"),
            fallback=tuple(str(f) for f in (fallback if isinstance(fallback, list) else [fallback])),
            thinking=spec.get("thinking"),
            timeout=float(spec.get("timeout", 40)),
        )
    return AIConfig(providers=providers, tasks=tasks, local_only=bool(raw.get("local_only", False)))
