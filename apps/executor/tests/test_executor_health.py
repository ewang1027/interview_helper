"""Surface tests for the executor.

The Phase 0 file here carried `test_no_execute_endpoint_yet`, a deliberate guard against
an execution path landing without its isolation tests. `/execute` has now landed *with*
those tests (`test_sandbox_escape.py`, marked `sandbox`), so the guard is replaced rather
than deleted: the assertion below keeps the same intent by pinning the endpoint's
contract, and the escape suite is what actually discharges the original obligation.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from executor.main import app

client = TestClient(app)


def test_health() -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_execute_rejects_a_malformed_request() -> None:
    """`extra="forbid"` plus required fields — a request missing its entrypoint or
    carrying a typo'd limit must be refused, not run with a default cap."""
    assert client.post("/execute", json={}).status_code == 422
    assert (
        client.post(
            "/execute",
            json={
                "language": "python",
                "source": "",
                "entrypoint": "f",
                "tests": [{"input": [1], "expected": 1}],
                "wall_millis": 100,
            },
        ).status_code
        == 422
    )


def test_execute_requires_at_least_one_test() -> None:
    resp = client.post(
        "/execute",
        json={"language": "python", "source": "", "entrypoint": "f", "tests": []},
    )
    assert resp.status_code == 422


def test_execute_refuses_an_unsupported_language_without_running_anything() -> None:
    """Returns a result rather than raising: the caller records a failed grading either
    way, and an exception would lose the reason. Reaches no sandbox, so it needs no
    Docker and stays in the default suite."""
    resp = client.post(
        "/execute",
        json={
            "language": "cpp",
            "source": "int main(){}",
            "entrypoint": "f",
            "tests": [{"input": [1], "expected": 1}],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["outcome"] == "harness_error"
    assert "not supported" in body["detail"]


def test_probe_rejects_a_request_it_could_not_fit() -> None:
    """Two sizes cannot produce a growth exponent. Refusing here is better than running
    two containers and reporting `inconclusive` afterwards."""
    resp = client.post(
        "/probe",
        json={
            "language": "python",
            "source": "def f(xs):\n    return xs\n",
            "entrypoint": "f",
            "generator": "def make_input(n):\n    return [list(range(n))]\n",
            "sizes": [100, 200],
            "target": "O(n)",
        },
    )
    assert resp.status_code == 422


def test_probe_refuses_an_unsupported_language_as_a_verdict_not_an_error() -> None:
    resp = client.post(
        "/probe",
        json={
            "language": "cpp",
            "source": "int main(){}",
            "entrypoint": "f",
            "generator": "",
            "sizes": [100, 200, 400],
            "target": "O(n)",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["verdict"] == "inconclusive"
    assert "not supported" in body["detail"]
