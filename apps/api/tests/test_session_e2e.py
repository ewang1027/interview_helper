"""One scripted session, end to end. Marked `e2e` — run via `make test-e2e`.

Needs **both** a live Postgres (`make dev && make seed`) and real Docker, because it is
the only test that runs the whole thing with nothing stubbed: the API talks to a real
executor process over a real socket, that executor launches real containers, and the
grades land in real rows.

That socket is the point. Every other test injects the executor app in-process, so the
`EXECUTOR_URL` -> `ExecutorClient()` -> HTTP path — the one a deployment actually uses —
was never exercised by anything. This is what covers it.

The Makefile has carried a `test-e2e` target since Phase 0 with nothing behind it. This
is the first thing behind it.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.settings import get_settings
from corpus.loader import load_items

pytestmark = pytest.mark.e2e

# The naive backward scan from docs/BUILDLOG.md: correct, and quadratic on ascending
# input. It passes every test i.code.0002 ships, so only the probe can mark it down.
QUADRATIC_SPANS = (
    "def pressure_spans(readings):\n"
    "    out = []\n"
    "    for i in range(len(readings)):\n"
    "        span, j = 1, i - 1\n"
    "        while j >= 0 and readings[j] <= readings[i]:\n"
    "            span += 1\n"
    "            j -= 1\n"
    "        out.append(span)\n"
    "    return out\n"
)


def _port_of(url: str) -> int:
    return int(url.rsplit(":", 1)[-1])


@pytest.fixture(scope="module")
def executor_server() -> Any:
    """A real executor process on the port `EXECUTOR_URL` names."""
    url = get_settings().executor_url
    port = _port_of(url)
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            pytest.skip(f"something is already listening on {port}; not starting a second executor")

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "executor.main:app",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
    )
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"executor exited with {proc.returncode} before answering")
        try:
            if httpx.get(f"{url}/health", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.2)
    else:
        proc.kill()
        raise RuntimeError(f"executor never came up on {url}")

    yield url
    proc.terminate()
    proc.wait(timeout=10)


def test_a_coding_session_runs_from_plan_to_report(executor_server, created_sessions) -> None:
    client = TestClient(app)

    created = client.post("/api/v1/sessions", json={"mode": "coding", "budget_minutes": 45}).json()
    created_sessions.append(created["id"])
    planned = [entry["item_id"] for entry in created["plan"]["items"]]
    assert planned == ["i.code.0001", "i.code.0002"], planned

    # A correct solution, and a correct-but-quadratic one. The pair is the whole point:
    # both pass every test they are given, and the report has to tell them apart.
    items = {item.id: item for item in load_items()}
    submissions = {
        "i.code.0001": (items["i.code.0001"].grading or {})["reference_solutions"]["python"],
        "i.code.0002": QUADRATIC_SPANS,
    }
    for item_id, source in submissions.items():
        resp = client.post(
            f"/api/v1/sessions/{created['id']}/submissions",
            json={"item_id": item_id, "kind": "code", "language": "python", "content": source},
        )
        assert resp.status_code == 202, resp.text

    detail = client.get(f"/api/v1/sessions/{created['id']}").json()
    assert detail["state"] == "complete", detail["items"]

    report = client.get(f"/api/v1/sessions/{created['id']}/report").json()
    scores = {row["item_id"]: row["score"] for row in report["items"]}
    assert scores["i.code.0001"] == pytest.approx(1.0)
    assert scores["i.code.0002"] == pytest.approx(0.75)

    quadratic = next(r for r in report["items"] if r["item_id"] == "i.code.0002")
    assert quadratic["detail"]["complexity"] == "slower_than_target"
    assert quadratic["detail"]["complexity_slope"] > 1.65

    # Eight evidence rows: four concepts on each item, primary at full confidence.
    assert len(report["evidence"]) == 8
    primary = [row for row in report["evidence"] if row["concept_id"] == "monotonic-stack"]
    assert primary and primary[0]["confidence"] == pytest.approx(0.9)
    assert primary[0]["score"] == pytest.approx(0.75)
