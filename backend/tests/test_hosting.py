"""Where Lingo OS runs: this laptop (the phone syncs with it) or the cloud server (laptop and phone both use it)."""

from __future__ import annotations

import dataclasses

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from app.db import settings_store
from app.main import create_app
from app.services import hosting


def test_a_laptop_starts_local_and_can_switch_to_the_cloud_and_back(client) -> None:
    assert client.get("/api/hosting").json() == {"role": "laptop", "mode": "local", "cloud_url": None}
    with client.app.state.engine.begin() as conn:
        settings_store.put(conn, "sync.enabled", True)

    # cloud mode needs an address; a bare name gets https://
    assert client.put("/api/hosting", json={"mode": "cloud"}).status_code == 422
    assert client.put("/api/hosting", json={"mode": "cloud", "cloud_url": "not an address!"}).status_code == 422
    saved = client.put("/api/hosting", json={"mode": "cloud", "cloud_url": "lingo-os.tail1234.ts.net/"}).json()
    assert saved == {"role": "laptop", "mode": "cloud", "cloud_url": "https://lingo-os.tail1234.ts.net"}

    # the phone now pairs with the server: this laptop stops listening and refuses to pair or listen again
    assert client.get("/api/sync/status").json()["enabled"] is False
    assert client.post("/api/sync/pair", json={"name": "Pixel"}).status_code == 409
    assert client.post("/api/sync/enable", json={"enabled": True}).status_code == 409

    # back to the laptop: the address is remembered, phone sync can be turned on again
    back = client.put("/api/hosting", json={"mode": "local"}).json()
    assert back == {"role": "laptop", "mode": "local", "cloud_url": "https://lingo-os.tail1234.ts.net"}
    assert client.post("/api/sync/enable", json={"enabled": True}).status_code == 200


def test_a_server_is_the_hub_itself_and_does_not_switch(cfg, monkeypatch) -> None:
    monkeypatch.setenv("LINGO_PUBLIC_URL", "https://lingo.tail1234.ts.net")
    server_cfg = dataclasses.replace(cfg, public_url="https://lingo.tail1234.ts.net", sync_on_main=True)
    with TestClient(create_app(server_cfg, run_jobs=False)) as server:
        assert server.get("/api/hosting").json()["role"] == "server"
        assert server.put("/api/hosting", json={"mode": "cloud", "cloud_url": "https://x.example"}).status_code == 422


def test_the_scheduled_tasks_skip_on_a_laptop_that_uses_the_cloud(cfg, monkeypatch) -> None:
    from app import cli

    monkeypatch.setenv("LINGO_DATA_DIR", str(cfg.data_dir))
    monkeypatch.setattr(cli, "load_config", lambda: cfg)
    app_ = create_app(cfg, run_jobs=False)
    with app_.state.engine.begin() as conn:
        hosting.put(conn, cfg, "cloud", "https://lingo-os.tail1234.ts.net")
    for command in (["update-content", "--json"], ["evolve-profile", "--no-llm", "--json"]):
        result = CliRunner().invoke(cli.app, command)
        assert result.exit_code == 0, result.output
        assert "Skipped" in result.output and "lingo-os.tail1234.ts.net" in result.output


def test_checking_an_address_that_does_not_answer(client) -> None:
    answer = client.post("/api/hosting/check", json={"mode": "cloud", "cloud_url": "http://127.0.0.1:9"}).json()
    assert answer["url"] == "http://127.0.0.1:9" and answer["reachable"] is False
