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
    kind: str  # gemini | anthropic | openai_compatible | ollama | fake
    api_key_env: str | None = None
    base_url: str | None = None
    default_model: str | None = None  # used when a task's model doesn't exist on this provider
    prices: dict[str, dict[str, float]] = field(default_factory=dict)  # model -> {in, out} USD per million tokens
    label: str | None = None  # set for the providers a learner can choose in Settings ("Gemini", "Claude", "ChatGPT")
    key_url: str | None = None  # where to create an API key
    models: dict[str, str] = field(default_factory=dict)  # tier ('fast' | 'smart') -> model

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
        if self.kind in {"gemini", "anthropic"} and not self.api_key:
            return f"no {self.api_key_env or 'API key'} set"
        if self.kind == "openai_compatible" and not self.base_url:
            return "no base_url configured"
        if self.kind == "openai_compatible" and self.api_key_env and not self.api_key and not self.is_local:
            return f"no {self.api_key_env} set"
        return None

    def model_for(self, tier: str | None) -> str | None:
        return (self.models.get(tier) if tier else None) or self.default_model


@dataclass(frozen=True)
class TaskRoute:
    task: str
    use: str
    model: str
    temperature: float | None = None
    fallback: tuple[str, ...] = ()
    thinking: str | None = None  # 'off' asks the model to answer without thinking first (faster)
    timeout: float = 40.0
    tier: str | None = None  # 'fast' | 'smart': the chosen provider's model for that tier (instead of `use` + `model`)


@dataclass(frozen=True)
class AIConfig:
    providers: dict[str, ProviderConfig]
    tasks: dict[str, TaskRoute]
    local_only: bool = False

    @property
    def choosable(self) -> list[str]:
        """Providers a learner can pick in Settings, in the order 'Auto' tries them."""
        return [name for name, p in self.providers.items() if p.label]


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
            label=spec.get("label"),
            key_url=spec.get("key_url"),
            models={str(k): str(v) for k, v in (spec.get("models") or {}).items()},
        )
        for name, spec in (raw.get("providers") or {}).items()
    }
    tasks = {}
    for task, spec in (raw.get("tasks") or {}).items():
        fallback = spec.get("fallback") or []
        tasks[task] = TaskRoute(
            task=task,
            use=str(spec.get("use") or ("" if spec.get("tier") else "cloud")),
            model=str(spec.get("model", "")),
            temperature=spec.get("temperature"),
            fallback=tuple(str(f) for f in (fallback if isinstance(fallback, list) else [fallback])),
            thinking=spec.get("thinking"),
            timeout=float(spec.get("timeout", 40)),
            tier=spec.get("tier"),
        )
    return AIConfig(providers=providers, tasks=tasks, local_only=bool(raw.get("local_only", False)))
