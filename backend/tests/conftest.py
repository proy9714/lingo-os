from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import AppConfig, load_config
from app.main import create_app

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def cfg(tmp_path: Path) -> AppConfig:
    base = load_config(data_dir=tmp_path / "data")
    return dataclasses.replace(base, tracker_path=FIXTURES / "tracker", starting_languages=("de", "es", "ja"), default_language="de")


@pytest.fixture
def client(cfg: AppConfig):
    with TestClient(create_app(cfg, run_jobs=False)) as test_client:
        yield test_client
