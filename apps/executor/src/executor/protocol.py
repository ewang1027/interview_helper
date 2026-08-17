"""The `/execute` request and response contract.

Shaped by `docs/API.md`'s `run_code` tool, which is the only way code runs:
`{ language, source, test_selection } -> { passed, total, failures[], wall_ms, peak_rss }`.

This module is deliberately free of any execution or Docker logic so the contract can be
imported and asserted against without pulling in the sandbox.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Language = Literal["python", "cpp"]

# Why an execution ended. `ok` means the harness ran to completion and the counts below
# are meaningful; every other value means they are not, and the caller must treat the
# run as a grading *failure* rather than a zero score. docs/GRADING.md: "a grader crash
# is a failed grading, never a silent pass or a default score."
Outcome = Literal[
    "ok",
    "timeout",
    "out_of_memory",
    "pid_limit",
    "compile_error",
    "harness_error",
]


class TestFailure(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    kind: Literal["example", "edge", "stress", "adversarial"] = "example"
    message: str


class ExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    language: Language
    source: str
    tests: str
    # Empty selection means "run every test", matching run_code's optional selection.
    test_selection: tuple[str, ...] = ()
    wall_ms: int | None = Field(default=None, gt=0)
    memory_mb: int | None = Field(default=None, gt=0)


class ExecuteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome: Outcome
    passed: int = 0
    total: int = 0
    failures: tuple[TestFailure, ...] = ()
    wall_ms: int = 0
    peak_rss_kb: int = 0
    # Populated on compile_error / harness_error. Truncated by the runner — an
    # unbounded stderr from untrusted code is itself a denial-of-service vector.
    detail: str = ""

    @property
    def is_gradeable(self) -> bool:
        """Only an `ok` run produces counts a grader may score. Anything else is a
        failed grading — see docs/GRADING.md's "failure is a failure"."""
        return self.outcome == "ok"
