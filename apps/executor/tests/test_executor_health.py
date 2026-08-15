"""Phase 0 smoke tests for the executor surface.

The `sandbox`-marked isolation tests arrive in Phase 2 alongside `POST /execute`.
Until then there is no execution path, so there is nothing to escape from.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from executor.main import app

client = TestClient(app)


def test_health() -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_no_execute_endpoint_yet() -> None:
    """Guards against an execution path landing without its isolation tests."""
    assert client.post("/execute", json={}).status_code == 404
