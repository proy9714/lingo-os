"""API keys pasted in Settings: kept in .env on this computer (git-ignored) and applied at once."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import set_key, unset_key


def save(env_file: Path, name: str, key: str) -> None:
    """Write `name=key` to .env (or remove it when `key` is empty) and update this process's environment."""
    if key:
        env_file.touch(exist_ok=True)
        set_key(str(env_file), name, key, quote_mode="never")
        os.environ[name] = key
    else:
        if env_file.exists():
            unset_key(str(env_file), name, quote_mode="never")
        os.environ.pop(name, None)
