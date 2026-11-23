"""ULIDs: 128-bit ids that sort by creation time (48-bit ms timestamp + 80 random bits)."""

from __future__ import annotations

import os
import time

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base32


def new_ulid(ms: int | None = None) -> str:
    timestamp = int(time.time() * 1000) if ms is None else ms
    if not 0 <= timestamp < 1 << 48:
        raise ValueError("timestamp out of ULID range")
    value = (timestamp << 80) | int.from_bytes(os.urandom(10), "big")
    chars = []
    for _ in range(26):
        chars.append(_ALPHABET[value & 31])
        value >>= 5
    return "".join(reversed(chars))


def ulid_timestamp_ms(ulid: str) -> int:
    value = 0
    for char in ulid.upper():
        value = value * 32 + _ALPHABET.index(char)
    return value >> 80
