"""Lingo OS on a server: a public address for phones, sign-in with an access token, phones syncing on the main port."""

from __future__ import annotations

import dataclasses
import json

import pytest
from fastapi.testclient import TestClient

from app.db import settings_store
from app.main import create_app
from app.sync import hub
from test_sync_hub import Phone

TOKEN = "correct-horse-battery-staple"


@pytest.fixture
def server(cfg, monkeypatch):
    monkeypatch.setenv("LINGO_PUBLIC_URL", "https://lingo.tail1234.ts.net")
    server_cfg = dataclasses.replace(cfg, access_token=TOKEN, public_url="https://lingo.tail1234.ts.net", sync_on_main=True)
    with TestClient(create_app(server_cfg, run_jobs=False), base_url="https://lingo.tail1234.ts.net") as test_client:
        yield test_client


def signed_in(client: TestClient) -> TestClient:
    response = client.post("/login", data={"token": TOKEN}, follow_redirects=False)
    assert response.status_code == 303 and "lingo_access" in response.headers["set-cookie"]
    return client


def test_the_api_asks_to_sign_in_but_health_and_the_login_page_dont(server) -> None:
    assert server.get("/api/settings").status_code == 401
    assert server.get("/api/health").status_code == 200
    assert "Access token" in server.get("/login").text
    assert server.post("/login", data={"token": "nope"}, follow_redirects=False).status_code == 401
    assert server.get("/api/settings", headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 200
    assert signed_in(server).get("/api/settings").status_code == 200
    server.get("/logout", follow_redirects=False)
    server.cookies.clear()
    assert server.get("/api/settings").status_code == 401


def test_phones_get_the_public_address_first_and_sync_through_the_main_port(server) -> None:
    signed_in(server)
    with server.app.state.engine.begin() as conn:
        settings_store.put(conn, "sync.enabled", True)
    offer = server.post("/api/sync/pair", json={"name": "Pixel"}).json()
    qr = json.loads(offer["qr"])
    assert qr["hub"][0] == "https://lingo.tail1234.ts.net"
    phone_client = TestClient(server.app, base_url="https://lingo.tail1234.ts.net")  # no cookie: phones use their key
    phone = Phone(phone_client, qr)
    status, result = phone.call("/sync/pair", {"name": "Pixel"})
    assert status == 200 and result["paired"]
    settings = phone.rpc("GET", "/api/settings")
    assert settings["status"] == 200 and "active_language" in settings["json"]  # forwarded past the sign-in
    assert phone_client.get("/api/settings").status_code == 401  # but the phone's own cookie-less calls are not


def test_full_addresses_with_a_scheme_and_port_are_kept(client, monkeypatch) -> None:
    monkeypatch.delenv("LINGO_PUBLIC_URL", raising=False)
    monkeypatch.delenv("LINGO_SYNC_ON_MAIN", raising=False)
    with client.app.state.engine.begin() as conn:
        # on a laptop: a bare https name means the host (its listener is plain http), a named port is kept as it is
        saved = hub.set_extra_addresses(conn, ["https://lingo.example.org", "laptop.tail1234.ts.net:9999/x", "http://100.64.1.2:8788"])
        assert saved == ["lingo.example.org", "laptop.tail1234.ts.net", "http://100.64.1.2:8788"]
        urls = hub.hub_urls(conn, 8788)
        assert "http://lingo.example.org:8788" in urls and "http://100.64.1.2:8788" in urls
        # on a server a full address is kept
        monkeypatch.setenv("LINGO_SYNC_ON_MAIN", "1")
        assert hub.set_extra_addresses(conn, ["https://lingo.example.org"]) == ["https://lingo.example.org"]
        assert "https://lingo.example.org" in hub.hub_urls(conn, 8788)
    with pytest.raises(ValueError):
        with client.app.state.engine.begin() as conn:
            hub.set_extra_addresses(conn, ["not an address!"])
