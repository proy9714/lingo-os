from __future__ import annotations

import json
import socket
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db import settings_store
from app.sync.crypto import b64d, open_envelope, seal
from app.sync.hlc import HybridClock
from app.sync.ids import new_ulid
from app.sync.server import Listener, create_sync_app


class Phone:
    """What the app on the phone does: seal requests with the key from the QR code."""

    def __init__(self, sync: TestClient, qr: dict) -> None:
        self.sync, self.qr = sync, qr
        self.device, self.token, self.key = qr["device"], qr["token"], b64d(qr["key"])
        self.clock = HybridClock(new_ulid())

    def call(self, path: str, message: dict, *, ts: float | None = None, key: bytes | None = None):
        body = {"device": self.device, **seal(key or self.key, self.device, {"ts": ts or time.time(), "token": self.token, **message})}
        response = self.sync.post(path, json=body)
        if response.status_code != 200:
            return response.status_code, response.json()
        return 200, open_envelope(self.key, self.device, response.json())

    def rpc(self, method: str, path: str, body=None, query=None):
        return self.call("/sync/rpc", {"method": method, "path": path, "body": body, "query": query})[1]

    def event(self, entity: str, payload: dict, key: str = "") -> dict:
        return {"event_id": new_ulid(), "hlc": self.clock.tick(), "entity": entity, "entity_key": key, "op": "insert", "payload": payload}


@pytest.fixture
def paired(client, cfg):
    engine = client.app.state.engine
    with engine.begin() as conn:
        settings_store.put(conn, "sync.enabled", True)
    offer = client.post("/api/sync/pair", json={"name": "Pixel"}).json()
    qr = json.loads(offer["qr"])
    assert qr["v"] == 1 and qr["hub"][0].startswith("http://") and qr["device"] == offer["device_id"]
    sync = TestClient(create_sync_app(client.app, engine, cfg))
    phone = Phone(sync, qr)
    status, result = phone.call("/sync/pair", {"name": "Pixel"})
    assert status == 200 and result == {"device_id": qr["device"], "paired": True}
    return phone


def test_pairing_needs_sync_on_and_works_once(client, cfg, paired) -> None:
    devices = client.get("/api/sync/status").json()["devices"]
    assert [(d["name"], d["kind"]) for d in devices if d["kind"] == "android"] == [("Pixel", "android")]
    status, error = paired.call("/sync/pair", {"name": "again"})
    assert status == 403 and "already used" in error["error"]
    with client.app.state.engine.begin() as conn:
        settings_store.put(conn, "sync.enabled", False)
    assert client.post("/api/sync/pair", json={}).status_code == 409


def test_rpc_reaches_the_app_but_not_device_management(paired) -> None:
    settings = paired.rpc("GET", "/api/settings")
    assert settings["status"] == 200 and "active_language" in settings["json"]
    blocked = paired.rpc("GET", "/api/sync/status")
    assert blocked["status"] == 403
    assert paired.rpc("GET", "/etc/passwd")["status"] == 403


def test_bad_key_old_requests_and_removed_phones_are_refused(client, paired) -> None:
    status, _ = paired.call("/sync/rpc", {"method": "GET", "path": "/api/settings"}, key=b"\x00" * 32)
    assert status == 403
    status, error = paired.call("/sync/rpc", {"method": "GET", "path": "/api/settings"}, ts=time.time() - 3600)
    assert status == 403 and "too old" in error["error"]
    client.delete(f"/api/devices/{paired.device}")
    status, error = paired.call("/sync/rpc", {"method": "GET", "path": "/api/settings"})
    assert status == 403 and "pair it again" in error["error"]


def test_a_trusted_phone_is_still_checked_and_removing_it_takes_effect_at_once(client, paired) -> None:
    assert paired.rpc("GET", "/api/settings")["status"] == 200  # now trusted for a minute
    with client.app.state.engine.connect() as conn:
        seen = conn.execute(text("SELECT last_seen_at FROM devices WHERE id = :d"), {"d": paired.device}).scalar()
    assert paired.rpc("GET", "/api/settings")["status"] == 200
    with client.app.state.engine.connect() as conn:  # a trusted phone's requests don't write to the database
        assert conn.execute(text("SELECT last_seen_at FROM devices WHERE id = :d"), {"d": paired.device}).scalar() == seen
    real = paired.token
    paired.token = "wrong"
    status, error = paired.call("/sync/rpc", {"method": "GET", "path": "/api/settings"})
    assert status == 403 and "pair it again" in error["error"]
    paired.token = real
    assert paired.rpc("GET", "/api/settings")["status"] == 200
    client.delete(f"/api/devices/{paired.device}")
    status, error = paired.call("/sync/rpc", {"method": "GET", "path": "/api/settings"})
    assert status == 403 and "pair it again" in error["error"]


def test_outbox_is_applied_once_with_last_writer_wins(client, paired) -> None:
    session = new_ulid()
    events = [
        paired.event("lookup", {"lang": "de", "lemma": "Kiste", "reading": "", "pos": "NOUN"}),
        paired.event("word_status", {"lang": "de", "lemma": "Kiste", "reading": "", "pos": "NOUN", "status": "learning", "save": True,
                                     "context": {"sentence": "Die Kiste ist schwer."}}),
        paired.event("activity", {"client_uuid": session, "lang": "de", "activity": "reading", "started_at": "2026-11-20T08:00:00.000Z",
                                  "ended_at": "2026-11-20T08:10:00.000Z", "active_seconds": 600}),
    ]
    status, result = paired.call("/sync/push", {"events": events})
    assert status == 200 and (result["applied"], result["duplicates"], result["errors"]) == (3, 0, [])
    again = paired.call("/sync/push", {"events": events})[1]
    assert again["duplicates"] == 3  # retries never double-count

    longer = paired.event("activity", {"client_uuid": session, "lang": "de", "activity": "reading",
                                       "started_at": "2026-11-20T08:00:00.000Z", "active_seconds": 900})
    assert paired.call("/sync/push", {"events": [longer]})[1]["merged"] == 1

    # a later status change on the laptop beats an older one from the phone
    old = paired.event("word_status", {"lang": "de", "lemma": "Kiste", "reading": "", "status": "known"})
    client.post("/api/vocab/status", json={"lang": "de", "lemma": "Kiste", "status": "familiar"})
    with client.app.state.engine.begin() as conn:
        conn.execute(text("UPDATE user_words SET updated_hlc = NULL, status_changed_at = '2099-01-01T00:00:00.000Z'"))
    assert paired.call("/sync/push", {"events": [old]})[1]["superseded"] == 1
    with client.app.state.engine.begin() as conn:
        conn.execute(text("UPDATE user_words SET status_changed_at = '2026-11-20T09:00:00.000Z', last_lookup_at = NULL"))

    with client.app.state.engine.connect() as conn:
        word = conn.execute(text("SELECT status, saved, lookups FROM user_words")).first()
        seconds = conn.execute(text("SELECT active_seconds FROM activity_sessions WHERE client_uuid = :u"), {"u": session}).scalar()
        context = conn.execute(text("SELECT sentence FROM word_contexts")).scalar()
    assert word == ("familiar", 1, 1) and seconds == 900 and context == "Die Kiste ist schwer."

    pulled = paired.call("/sync/pull", {"since": None})[1]
    assert [(w["lemma"], w["status"]) for w in pulled["words"]] == [("Kiste", "familiar")]
    assert paired.call("/sync/pull", {"since": pulled["until"]})[1]["words"] == []


def test_offline_pack_for_a_text(client, paired) -> None:
    item = client.post("/api/content/text", json={"lang": "de", "title": "Notiz", "text": "Die Kinder spielen im Park.\n\nDann gehen sie nach Hause."}).json()
    pack = paired.rpc("GET", f"/api/packs/{item['id']}")
    assert pack["status"] == 200
    data = pack["json"]
    assert data["kind"] == "text" and data["item"]["title"] == "Notiz"
    assert data["pages"][0]["paragraphs"][0]["text"] == "Die Kinder spielen im Park."
    assert any(t["display"] == "Park" for t in data["pages"][0]["paragraphs"][0]["tokens"])
    listed = paired.rpc("GET", "/api/packs")["json"]
    assert [(p["item_id"], p["status"]) for p in listed] == [(item["id"], "ready")]
    assert client.get("/api/packs").status_code == 400  # only phones have packs


def test_listener_starts_and_stops(client, cfg) -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    listener = Listener()
    listener.start(create_sync_app(client.app, client.app.state.engine, cfg), port, host="127.0.0.1")
    try:
        assert listener.running
        assert httpx.post(f"http://127.0.0.1:{port}/sync/hello").json() == {"app": "lingo-os", "sync": 1}
    finally:
        listener.stop()
    assert not listener.running


def test_a_test_server_never_takes_a_phone(client, monkeypatch) -> None:
    status = client.get("/api/sync/status").json()
    assert status["data_dir"] and status["temporary"] is True and status["allowed"] is True  # tests run in a temp folder
    monkeypatch.setenv("LINGO_PHONE_SYNC", "off")
    refused = client.post("/api/sync/enable", json={"enabled": True})
    assert refused.status_code == 409 and "LINGO_PHONE_SYNC" in refused.json()["detail"]
    status = client.get("/api/sync/status").json()
    assert status["allowed"] is False and status["enabled"] is False


def test_away_from_home_addresses_reach_paired_phones(client, paired, monkeypatch) -> None:
    from app.sync import hub

    monkeypatch.setattr(hub, "tailscale_addresses", lambda: ["100.101.102.103"])
    status = client.put("/api/sync/addresses", json={"addresses": ["laptop.tail1234.ts.net", " https://laptop.tail1234.ts.net/ "]}).json()
    assert status["extra_addresses"] == ["laptop.tail1234.ts.net"] and status["tailscale"] == ["100.101.102.103"]
    assert client.put("/api/sync/addresses", json={"addresses": ["not a host!"]}).status_code == 422

    code, hello = paired.call("/sync/where", {})  # a phone paired before: learns the new addresses
    assert code == 200
    assert any("100.101.102.103" in h for h in hello["hubs"]) and any("laptop.tail1234.ts.net" in h for h in hello["hubs"])
    assert hello["hubs"][0] not in {h for h in hello["hubs"] if "100.101" in h or "ts.net" in h}  # home Wi-Fi first

    qr = json.loads(client.post("/api/sync/pair", json={"name": "Tablet"}).json()["qr"])
    assert any("ts.net" in h for h in qr["hub"])  # and a phone paired now gets them in its code
