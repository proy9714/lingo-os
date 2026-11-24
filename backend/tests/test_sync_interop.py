"""The phone's WebCrypto code (frontend/src/sync/crypto.ts) and the hub's Python must read each other's envelopes."""

from __future__ import annotations

import json
import os
import shutil
import subprocess

import pytest

from app.config import ROOT
from app.sync.crypto import b64e, open_envelope, seal

NODE = shutil.which("node")
SCRIPT = """
const { importKey, seal, openEnvelope } = await import(process.env.CRYPTO_TS);
const input = JSON.parse(process.env.INPUT);
const key = await importKey(input.key);
const opened = await openEnvelope(key, input.device, input.envelope);
const reply = await seal(key, input.device, { echo: opened, from: "phone" });
console.log(JSON.stringify(reply));
"""


@pytest.mark.skipif(NODE is None, reason="Node is not installed")
def test_python_and_webcrypto_envelopes_match() -> None:
    key, device = os.urandom(32), "01PHONEDEVICE000000000000A"
    message = {"ts": 1, "path": "/api/settings", "word": "Größe 日本語"}
    crypto_ts = (ROOT / "frontend" / "src" / "sync" / "crypto.ts").resolve().as_uri()
    env = {
        **os.environ,
        "CRYPTO_TS": crypto_ts,
        "INPUT": json.dumps({"key": b64e(key), "device": device, "envelope": seal(key, device, message)}),
    }
    result = subprocess.run(
        [NODE, "--input-type=module", "-e", SCRIPT], env=env, capture_output=True, text=True, timeout=60
    )
    if result.returncode != 0 and "Unknown file extension" in result.stderr:
        pytest.skip("this Node can't run TypeScript directly")
    assert result.returncode == 0, result.stderr
    reply = json.loads(result.stdout.strip().splitlines()[-1])
    assert open_envelope(key, device, reply) == {"echo": message, "from": "phone"}
