"""Shared fixtures."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

# Ensure Stockfish path before app import side effects
os.environ.setdefault("STOCKFISH_PATH", "/usr/games/stockfish")


@pytest.fixture(scope="session")
def client() -> TestClient:
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def engine():
    from app.engine import get_engine

    eng = get_engine()
    eng.start()
    return eng
