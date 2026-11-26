"""The Wi-Fi listener for paired phones (ARCHITECTURE §6.13).

The main server stays bound to this laptop (127.0.0.1). This second, small server listens on the home network and
answers only encrypted requests from paired phones:

  POST /sync/hello   who are you (plain, nothing secret)
  POST /sync/pair    finish pairing with the one-time code from the QR
  POST /sync/rpc     an API call for the app on the phone, forwarded to the main app in-process
  POST /sync/push    the phone's offline outbox
  POST /sync/pull    word statuses changed since the phone's last sync

Every body except /hello is {"device": id, "n": nonce, "c": ciphertext}; requests older than five minutes are refused.
It is off until you turn it on in Settings.

A phone opening the app sends a burst of requests. So that each one doesn't re-read the hub secret, re-derive the key
and write "last seen" to the database, a phone that proved itself is trusted for a minute (removing it in Settings
forgets it at once). Database work runs in worker threads, so one slow request never holds up the others.
"""

from __future__ import annotations

import base64
import hmac
import threading
import time
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import Engine
from starlette.concurrency import run_in_threadpool

from app.config import AppConfig
from app.db import settings_store
from app.sync import apply as sync_apply
from app.sync import hub
from app.sync.crypto import EnvelopeError, hash_token, open_envelope, seal
from app.sync.hub import SyncAuthError, authenticate, confirm_pairing, device_key, pending_key

MAX_SKEW_SECONDS = 300
BLOCKED_PREFIXES = ("/api/sync", "/api/devices", "/api/ai/test", "/api/ai/keys", "/api/data")  # pairing and API keys stay on the laptop
TRUST_SECONDS = 60.0

# device id -> (key, hash of its token, trusted until): phones that proved themselves in the last minute
_trusted: dict[str, tuple[bytes, str, float]] = {}
_trusted_lock = threading.Lock()


def forget_device(device_id: str | None = None) -> None:
    """Stop trusting a phone at once (it was removed), or every phone (None)."""
    with _trusted_lock:
        if device_id is None:
            _trusted.clear()
        else:
            _trusted.pop(device_id, None)


def _trusted_key(device_id: str) -> tuple[bytes, str] | None:
    with _trusted_lock:
        entry = _trusted.get(device_id)
        if entry and entry[2] > time.monotonic():
            return entry[0], entry[1]
        _trusted.pop(device_id, None)
        return None


def _envelope(body: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    device = body.get("device")
    if not isinstance(device, str) or not device:
        raise EnvelopeError("missing device id")
    return device, body


def create_sync_app(main_app: FastAPI, engine: Engine, cfg: AppConfig, base: str = "/sync") -> FastAPI:
    """The sync endpoints. `base` is "/sync" for the Wi-Fi listener; "" when mounted at /sync on the main app."""
    app = FastAPI(title="Lingo OS sync", docs_url=None, redoc_url=None, openapi_url=None)
    # Any origin may call: every body is encrypted with a key only paired phones have. (The Android app uses native
    # HTTP and doesn't need this; it lets the phone mode be tried in an ordinary browser.)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["POST"], allow_headers=["Content-Type"])
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=main_app), base_url="http://hub", timeout=120)

    def forward_headers(device: str) -> dict[str, str]:
        # the phone already proved itself with its pairing key; on a server the API also wants the access token
        headers = {"X-Lingo-Device": device}
        if cfg.access_token:
            headers["Authorization"] = f"Bearer {cfg.access_token}"
        return headers

    def fail(status: int, message: str) -> JSONResponse:
        return JSONResponse({"error": message}, status_code=status)

    def unwrap(body: dict[str, Any], *, pairing: bool = False) -> tuple[str, bytes, dict[str, Any]]:
        device, envelope = _envelope(body)
        trusted = None if pairing else _trusted_key(device)
        token_hash: str | None = None
        if trusted:
            key, token_hash = trusted
        else:
            with engine.begin() as conn:
                key = pending_key(conn, cfg, device) if pairing else device_key(conn, cfg, device)
        if key is None:
            raise SyncAuthError("this pairing code is unknown or was already used")
        message = open_envelope(key, device, envelope)
        if abs(time.time() - float(message.get("ts", 0))) > MAX_SKEW_SECONDS:
            raise SyncAuthError("the request is too old (check the phone's clock)")
        if pairing:
            return device, key, message
        token = str(message.get("token", ""))
        if token_hash is not None:
            if not hmac.compare_digest(token_hash, hash_token(token)):
                forget_device(device)
                raise SyncAuthError("this phone isn't paired (or was removed); pair it again")
        else:
            with engine.begin() as conn:
                authenticate(conn, device, token)
            with _trusted_lock:
                _trusted[device] = (key, hash_token(token), time.monotonic() + TRUST_SECONDS)
        return device, key, message

    async def unwrap_async(request: Request, *, pairing: bool = False) -> tuple[str, bytes, dict[str, Any]]:
        body = await request.json()
        return await run_in_threadpool(unwrap, body, pairing=pairing)

    def _confirm(device: str, message: dict[str, Any]) -> dict[str, Any]:
        with engine.begin() as conn:
            return confirm_pairing(conn, device, message.get("token", ""), str(message.get("name", "Phone")))

    def _push(device: str, message: dict[str, Any]) -> dict[str, Any]:
        with engine.begin() as conn:
            return sync_apply.apply_events(conn, device, list(message.get("events") or []))

    def _where() -> list[str]:
        with engine.connect() as conn:
            port = int(settings_store.get(conn, "sync.port", hub.SYNC_PORT))
            return hub.hub_urls(conn, port)

    def _pull(message: dict[str, Any]) -> dict[str, Any]:
        with engine.connect() as conn:
            return sync_apply.changes_since(conn, message.get("since"))

    @app.post(f"{base}/hello")
    async def hello() -> dict[str, Any]:
        return {"app": "lingo-os", "sync": 1}

    @app.post(f"{base}/pair")
    async def pair(request: Request):
        try:
            device, key, message = await unwrap_async(request, pairing=True)
            result = await run_in_threadpool(_confirm, device, message)
        except (EnvelopeError, SyncAuthError, ValueError) as exc:
            return fail(403, str(exc))
        return seal(key, device, result)

    @app.post(f"{base}/rpc")
    async def rpc(request: Request):
        try:
            device, key, message = await unwrap_async(request)
        except (EnvelopeError, SyncAuthError, ValueError) as exc:
            return fail(403, str(exc))
        method = str(message.get("method", "GET")).upper()
        path = str(message.get("path", ""))
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"} or not path.startswith("/api/") or path.startswith(BLOCKED_PREFIXES):
            return seal(key, device, {"status": 403, "json": {"detail": "not available from the phone"}})
        response = await client.request(
            method, path, params=message.get("query") or None, json=message.get("body"),
            headers=forward_headers(device),
        )
        kind = response.headers.get("content-type", "")
        if kind.startswith("application/json"):
            out: dict[str, Any] = {"status": response.status_code, "json": response.json()}
        elif kind.startswith("text/"):
            out = {"status": response.status_code, "text": response.text}
        else:
            out = {"status": response.status_code, "type": kind, "b64": base64.b64encode(response.content).decode()}
        return seal(key, device, out)

    @app.post(f"{base}/push")
    async def push(request: Request):
        try:
            device, key, message = await unwrap_async(request)
            result = await run_in_threadpool(_push, device, message)
        except (EnvelopeError, SyncAuthError, ValueError) as exc:
            return fail(403, str(exc))
        return seal(key, device, result)

    @app.post(f"{base}/where")
    async def where(request: Request):
        """The laptop's current addresses: a phone paired at home learns a Tailscale address added later."""
        try:
            device, key, _message = await unwrap_async(request)
            hubs = await run_in_threadpool(_where)
        except (EnvelopeError, SyncAuthError, ValueError) as exc:
            return fail(403, str(exc))
        return seal(key, device, {"hubs": hubs})

    @app.post(f"{base}/pull")
    async def pull(request: Request):
        try:
            device, key, message = await unwrap_async(request)
            result = await run_in_threadpool(_pull, message)
        except (EnvelopeError, SyncAuthError, ValueError) as exc:
            return fail(403, str(exc))
        return seal(key, device, result)

    return app


class Listener:
    """Runs the sync app on 0.0.0.0:<port> in a background thread; can be started and stopped at runtime."""

    def __init__(self) -> None:
        self.server: Any = None
        self.thread: threading.Thread | None = None
        self.port: int | None = None
        self.error: str | None = None

    @property
    def running(self) -> bool:
        return bool(self.thread and self.thread.is_alive() and self.server and self.server.started)

    def start(self, app: FastAPI, port: int, host: str = "0.0.0.0") -> None:
        if self.thread and self.thread.is_alive():
            return
        import uvicorn

        # log_config/log_level None: leave logging as the main server set it up. A log level here would apply to the
        # shared "uvicorn.error" logger and hide the main server's "Application startup complete" line.
        config = uvicorn.Config(app, host=host, port=port, log_config=None, log_level=None, access_log=False)
        self.server = uvicorn.Server(config)
        self.port, self.error = port, None

        def run() -> None:
            try:
                self.server.run()
            except (OSError, SystemExit) as exc:  # port in use, firewall refusal
                self.error = str(exc) or "could not listen on the network"

        self.thread = threading.Thread(target=run, name="lingo-sync", daemon=True)
        self.thread.start()
        for _ in range(50):  # wait up to ~5 s for it to come up
            if self.server.started or not self.thread.is_alive():
                break
            time.sleep(0.1)
        if not self.server.started and not self.error:
            self.error = "the sync listener did not start"

    def stop(self) -> None:
        if self.server:
            self.server.should_exit = True
        if self.thread:
            self.thread.join(timeout=5)
        self.server = self.thread = None
