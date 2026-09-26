"""Health endpoint tests."""

from __future__ import annotations


def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["ready"] is True
    assert data["status"] == "ok"
    assert "stockfish" in data["engine"]
