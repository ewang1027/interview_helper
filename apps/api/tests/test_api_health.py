"""Phase 0 smoke tests for the API surface."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_health() -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_corpus_status_reports_the_shipped_taxonomy() -> None:
    resp = client.get("/corpus/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["concepts"] > 50
    assert set(body["concepts_by_domain"]) == {
        "coding",
        "quant",
        "system_design",
        "behavioral",
    }
