"""Smoke tests for the API surface — the routes that need no database."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_health() -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_health_stays_at_the_root() -> None:
    """It is what a load balancer polls, and the one route auth will exempt. Under the
    `/api/v1` prefix that exemption becomes a special case inside the auth dependency;
    outside it, the exemption is structural."""
    assert client.get("/api/v1/health").status_code == 404


def test_corpus_status_reports_the_shipped_taxonomy() -> None:
    resp = client.get("/api/v1/corpus/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["concepts"] > 50
    assert set(body["concepts_by_domain"]) == {
        "coding",
        "quant",
        "system_design",
        "behavioral",
    }


def test_the_unversioned_corpus_route_is_gone() -> None:
    """docs/API.md called this move owed. Pinning the 404 keeps it a decision rather than
    something a stray re-registration could quietly undo."""
    assert client.get("/corpus/status").status_code == 404


def test_a_malformed_body_is_problem_json() -> None:
    """RFC 9457 for every refusal, not FastAPI's `{"detail": ...}` — a client should be
    able to branch on `type` instead of matching on prose."""
    resp = client.post("/api/v1/sessions", json={"mode": "nonsense"})
    assert resp.status_code == 400
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["type"].endswith("/malformed-request")
    assert body["instance"] == "/api/v1/sessions"
    assert body["errors"]


# Every route the app serves. Pinned deliberately: docs/API.md carries a per-route "built /
# not built" column, and the two drift silently — a route added without its doc row reads
# as unbuilt to anyone planning Phase 5 against the spec, and a route removed leaves a row
# promising something that 404s.
SURFACE = {
    ("GET", "/health"),
    ("GET", "/api/v1/corpus/status"),
    ("GET", "/api/v1/mastery"),
    ("GET", "/api/v1/mastery/weaknesses"),
    ("GET", "/api/v1/mastery/{concept_id}"),
    ("POST", "/api/v1/mastery/recompute"),
    ("GET", "/api/v1/plan/next"),
    ("POST", "/api/v1/sessions"),
    ("GET", "/api/v1/sessions"),
    ("GET", "/api/v1/sessions/{session_id}"),
    ("POST", "/api/v1/sessions/{session_id}/submissions"),
    ("POST", "/api/v1/sessions/{session_id}/end"),
    ("GET", "/api/v1/sessions/{session_id}/report"),
}


def test_the_route_surface_is_what_the_api_doc_says_it_is() -> None:
    spec = client.get("/openapi.json")
    assert spec.status_code == 200, "the schema failed to generate, so /docs is broken too"

    served = {
        (method.upper(), path)
        for path, operations in spec.json()["paths"].items()
        for method in operations
    }
    assert served == SURFACE, (
        "the route surface changed — update docs/API.md's per-route status column, "
        f"then this set. added={sorted(served - SURFACE)} removed={sorted(SURFACE - served)}"
    )
