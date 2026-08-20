"""The `/execute` request and response contract.

Shaped by `docs/API.md`'s `run_code` tool, which is the only way code runs, and by
`gradingTests` in `packages/corpus/schema/item.schema.json`, which is what actually
supplies the tests.

This module is deliberately free of any execution or Docker logic so the contract can be
imported and asserted against without pulling in the sandbox.

**Corrected 2026-08-20.** The first version of this file typed `tests` as a single `str`,
assuming an item shipped test *source code*. It does not: `gradingTests.tests` is a list
of structured cases (`input`, `expected`, `kind`, `hidden`) plus a named `entrypoint` the
candidate implements. The contract was written before any corpus item existed and the
content disproved it. Kept as a note because guessing an interface ahead of its data is
how a contract ends up describing something nothing produces.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Language = Literal["python", "cpp"]
TestKind = Literal["example", "edge", "stress", "adversarial"]

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


class TestCase(BaseModel):
    """One graded case. `input` is the argument list the entrypoint is called with, so
    `input=[[1,2,3], 5]` means `entrypoint([1, 2, 3], 5)`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    input: tuple[Any, ...]
    expected: Any = None
    name: str = "test"
    # Mirrors the corpus schema's default. The kind is carried through to failures
    # because docs/GRADING.md weights evidence by it: failing an adversarial case is
    # weaker evidence of weakness than failing an example one.
    kind: TestKind = "edge"
    hidden: bool = True


class TestFailure(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    kind: TestKind = "example"
    message: str


class ExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    language: Language
    source: str
    entrypoint: str
    tests: tuple[TestCase, ...] = Field(min_length=1)
    # Empty selection means "run every test", matching run_code's optional selection.
    test_selection: tuple[str, ...] = ()
    wall_ms: int | None = Field(default=None, gt=0)
    memory_mb: int | None = Field(default=None, gt=0)

    def selected(self) -> tuple[TestCase, ...]:
        if not self.test_selection:
            return self.tests
        wanted = set(self.test_selection)
        return tuple(t for t in self.tests if t.name in wanted)


class ExecuteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome: Outcome
    passed: int = 0
    total: int = 0
    failures: tuple[TestFailure, ...] = ()
    wall_ms: int = 0
    peak_rss_kb: int = 0
    # Populated on compile_error / harness_error, and carries stdout/stderr otherwise.
    # Truncated by the runner — an unbounded stream from untrusted code is itself a
    # denial-of-service vector.
    detail: str = ""

    @property
    def is_gradeable(self) -> bool:
        """Only an `ok` run produces counts a grader may score. Anything else is a
        failed grading — see docs/GRADING.md's "failure is a failure"."""
        return self.outcome == "ok"


# --- Complexity probe ----------------------------------------------------------------

# What a growth measurement concluded. `inconclusive` is a real verdict rather than an
# error: the probe reports it whenever the data cannot carry a call, and it never
# penalises. Defined here rather than in `complexity` so the wire contract stays
# importable without the module that shells out to Docker.
Verdict = Literal["matches", "slower_than_target", "inconclusive"]


class ProbeRequest(BaseModel):
    """Run a submission at increasing *n* and judge its growth against `target`.

    Deliberately a separate contract from `ExecuteRequest`, not extra fields on it.
    docs/API.md's `run_code` is the interviewer agent's entire code-running surface and
    carries no probe fields; the probe is a *grading* step the agent never invokes, and
    keeping it off `/execute` keeps that surface as small as it is documented to be.

    `generator` is Python source defining `make_input(n)`. It arrives in the request
    because it lives in the item's `complexity_probe` — the caller holds the corpus, and
    this service deliberately holds none.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    language: Language
    source: str
    entrypoint: str
    generator: str
    # Three is the floor the fit needs, and matches `complexity_probe.sizes` minItems in
    # the corpus schema. Fewer is a caller bug worth a 422, not a silent `inconclusive`.
    sizes: tuple[int, ...] = Field(min_length=3)
    target: str | None = None
    repeats: int = Field(default=5, ge=1)
    wall_ms: int | None = Field(default=None, gt=0)
    memory_mb: int | None = Field(default=None, gt=0)


class ProbeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    verdict: Verdict
    slope: float | None = None
    points: tuple[tuple[int, float], ...] = ()
    target: str | None = None
    detail: str = ""

    @property
    def penalises(self) -> bool:
        """Only a confident `slower_than_target` may affect a score. Mirrors
        `executor.complexity.ProbeResult.penalises`, whose value this carries."""
        return self.verdict == "slower_than_target"
