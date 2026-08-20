"""Test doubles shared by the API's database-backed tests.

Not a conftest fixture: several tests want the class itself, to hand it a canned outcome
per test. Kept in one file because three copies of a `CodeRunner` would be three chances
to drift away from the Protocol the real client implements.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from api.executor_client import ProbeOutcome, RunResult


class FakeRunner:
    """A `CodeRunner` whose answers the test chooses, so no Docker is involved."""

    def __init__(self, run: RunResult | None = None, probe: ProbeOutcome | None = None) -> None:
        self.run = run or RunResult(outcome="ok", passed=0, total=0)
        self.probe_result = probe or ProbeOutcome(verdict="matches", slope=1.0)

    def run_tests(
        self,
        *,
        source: str,
        entrypoint: str,
        tests: Sequence[Mapping[str, Any]],
        language: str = "python",
        test_selection: Sequence[str] = (),
        wall_ms: int | None = None,
        memory_mb: int | None = None,
    ) -> RunResult:
        # `passed=0` on the canned result means "pass them all": the fake does not know how
        # many cases an item ships until it is handed them.
        return self.run.model_copy(
            update={"total": len(tests), "passed": self.run.passed or len(tests)}
        )

    def probe(
        self,
        *,
        source: str,
        entrypoint: str,
        generator: str,
        sizes: Sequence[int],
        target: str | None,
        language: str = "python",
        repeats: int = 5,
        wall_ms: int | None = None,
        memory_mb: int | None = None,
    ) -> ProbeOutcome:
        return self.probe_result
