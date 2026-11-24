"""Sync envelopes: AES-256-GCM with a per-phone key, bound to the device id.

The key travels once, inside the pairing QR code shown on the laptop's screen. After that every request and response
on the Wi-Fi listener is encrypted and authenticated, so no TLS certificates are needed on a home network.
The phone uses the browser's WebCrypto (AES-GCM), which produces the same format.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class EnvelopeError(Exception):
    pass


def b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def derive_key(secret: bytes, device_id: str) -> bytes:
    """Each phone gets its own key, derived from the hub's secret: nothing to store per device."""
    return hmac.new(secret, b"lingo-sync-key|" + device_id.encode(), hashlib.sha256).digest()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def seal(key: bytes, device_id: str, payload: Any) -> dict[str, str]:
    nonce = os.urandom(12)
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    return {"n": b64e(nonce), "c": b64e(AESGCM(key).encrypt(nonce, data, device_id.encode()))}


def open_envelope(key: bytes, device_id: str, envelope: dict[str, Any]) -> Any:
    try:
        plain = AESGCM(key).decrypt(b64d(envelope["n"]), b64d(envelope["c"]), device_id.encode())
    except (InvalidTag, KeyError, ValueError, TypeError) as exc:
        raise EnvelopeError("the message could not be decrypted (wrong key or tampered)") from exc
    return json.loads(plain)
