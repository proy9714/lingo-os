"""Searches written by the AI provider: once a day per language, and nothing breaks without AI."""

from __future__ import annotations

from app.ai.gateway import AIUnavailable, Gateway
from app.services.discover import ai_queries


def test_ai_searches_are_cached_for_the_day(client, monkeypatch) -> None:
    calls = []

    def fake(self, task, prompt, variables, schema, cache=True):
        calls.append(variables)
        return schema(queries=["Kochen  für Anfänger", "Wandern in den Alpen", "", "Berlin Geschichte", "zu viel"]), {}

    monkeypatch.setattr(Gateway, "structured", fake)
    engine, cfg = client.app.state.engine, client.app.state.cfg
    first = ai_queries(engine, cfg, "de", "A2")
    assert first == ["Kochen für Anfänger", "Wandern in den Alpen", "Berlin Geschichte", "zu viel"]
    assert ai_queries(engine, cfg, "de", "A2") == first and len(calls) == 1  # once a day
    assert calls[0]["language"] == "German" and calls[0]["level"] == "A2"


def test_without_ai_discovery_keeps_its_own_searches(client, monkeypatch) -> None:
    def off(self, *args, **kwargs):
        raise AIUnavailable("no key")

    monkeypatch.setattr(Gateway, "structured", off)
    assert ai_queries(client.app.state.engine, client.app.state.cfg, "es", "B1") == []
