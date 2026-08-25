"""The guards in front of the sandbox, and the startup sweep.

Everything here runs without Docker. What is being tested is the code that decides
*not* to reach the sandbox — a request in a language nothing runs, a selection matching
no test — and the rule those paths share: **an unrunnable request is a result, not an
HTTP error.** The caller records a failed grading either way, and raising here would lose
the reason.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from executor import main
from executor.main import app

client = TestClient(app)


def execute_body(**over: Any) -> dict[str, Any]:
    return {
        "language": "python",
        "source": "def solve(a):\n    return a\n",
        "entrypoint": "solve",
        "tests": [{"input": [1], "expected": 1, "name": "t1"}],
        **over,
    }


def probe_body(**over: Any) -> dict[str, Any]:
    return {
        "language": "python",
        "source": "def solve(a):\n    return a\n",
        "entrypoint": "solve",
        "generator": "def make_input(n):\n    return [list(range(n))]\n",
        "sizes": [10, 20, 40],
        "target": "linear",
        **over,
    }


# --- /execute ---------------------------------------------------------------------------


def test_an_unsupported_language_is_a_harness_error_not_a_500():
    """`cpp` is a valid `Language` in the protocol and not yet runnable. The request is
    well-formed, so refusing it with a 4xx would be wrong; it comes back as an outcome the
    caller can record."""
    response = client.post("/execute", json=execute_body(language="cpp"))

    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "harness_error"
    assert "cpp" in body["detail"]


def test_a_selection_matching_no_test_is_a_harness_error():
    """Not "zero tests passed", which would score as a wrong answer. Nothing ran."""
    response = client.post("/execute", json=execute_body(test_selection=["no-such-test"]))

    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "harness_error"
    assert "matched none" in body["detail"]


def test_neither_guard_reaches_the_sandbox(monkeypatch):
    """The point of both guards: no container is started for a request that cannot run."""
    started: list[Any] = []
    monkeypatch.setattr(main, "run_sandboxed", lambda *a, **k: started.append(a))

    client.post("/execute", json=execute_body(language="cpp"))
    client.post("/execute", json=execute_body(test_selection=["nope"]))

    assert started == []


# --- /probe ---------------------------------------------------------------------------


def test_an_unsupported_language_probe_is_inconclusive():
    """`inconclusive` rather than a failure: the probe exists to catch a slow-but-correct
    solution, and one that never ran has caught nothing — it has not proved anything
    either."""
    response = client.post("/probe", json=probe_body(language="cpp"))

    assert response.status_code == 200
    body = response.json()
    assert body["verdict"] == "inconclusive"
    assert body["target"] == "linear"
    assert "cpp" in body["detail"]


def test_the_probe_guard_does_not_run_a_probe(monkeypatch):
    ran: list[Any] = []
    monkeypatch.setattr(main, "run_probe", lambda *a, **k: ran.append(a))

    client.post("/probe", json=probe_body(language="cpp"))

    assert ran == []


# --- startup ----------------------------------------------------------------------------


def test_startup_sweeps_containers_orphaned_by_a_previous_run(monkeypatch, caplog):
    """`reap_orphans` had one definition and zero callers until it was hooked here. The
    paths that orphan a container are the ones where this process died, so startup is the
    only moment the sweep can see them."""
    monkeypatch.setattr(main, "reap_orphans", lambda: 3)

    with caplog.at_level("WARNING"), TestClient(app):
        pass

    assert any("reaped 3" in record.getMessage() for record in caplog.records)


def test_a_clean_startup_says_nothing(monkeypatch, caplog):
    """Silence when there was nothing to reap — a warning on every boot is a warning
    nobody reads."""
    monkeypatch.setattr(main, "reap_orphans", lambda: 0)

    with caplog.at_level("WARNING"), TestClient(app):
        pass

    assert not [r for r in caplog.records if "reaped" in r.getMessage()]


@pytest.mark.parametrize("endpoint", ["/execute", "/probe"])
def test_a_malformed_body_is_refused_rather_than_defaulted(endpoint):
    assert client.post(endpoint, json={}).status_code == 422
