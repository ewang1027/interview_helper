"""The API's one channel to the executor service.

`apps/api` never runs candidate code in its own process. It asks `apps/executor` to, over
HTTP, because that split *is* the trust boundary in docs/SECURITY.md: the service holding
the database and the model credentials is not the service running hostile code. This
module is the only place that boundary is crossed.

**The models below are deliberately a second copy of `executor.protocol`, not an import
of it.** Importing would make `api` depend on the package that owns the Docker-socket
launcher, and ship `executor.sandbox` inside the API image for the sake of three Pydantic
classes. The price of copying is drift, so `apps/api/tests/test_executor_contract.py`
validates every request body this module builds against the real `ExecuteRequest` /
`ProbeRequest` (both `extra="forbid"`, so a stray field fails) and asserts the response
fields and literal values match. Drift becomes a red test, not a wrong score.

Two failures are kept distinct because they mean opposite things:

- `ExecutorUnavailableError` — the service could not be reached, or did not answer in time.
  Says **nothing** about the submission. docs/API.md maps it to `503`; it must never be
  recorded as a zero.
- `ExecutorProtocolError` — the service answered, and the answer was not the contract.
  That is our bug, and calling it "unavailable" would be a lie that hides it.

A *failed run* — a timeout, an OOM kill, a candidate who never defined the entrypoint —
is neither. It comes back as a normal 200 with a non-`ok` outcome, because the caller has
to record it as a failed grading either way.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, NonNegativeInt, model_validator

from api.settings import get_settings

Language = Literal["python", "cpp"]
TestKind = Literal["example", "edge", "stress", "adversarial"]
Outcome = Literal["ok", "timeout", "out_of_memory", "pid_limit", "compile_error", "harness_error"]
Verdict = Literal["matches", "slower_than_target", "inconclusive"]

# How long to wait beyond the sandbox's own wall clock. Covers container start-up, image
# resolution and the round trip; the sandbox kills the container itself, so this only has
# to be longer than that, never a limit of its own.
_TRANSPORT_MARGIN_S = 20.0

# `run_probe`'s own defaults, mirrored so the timeout can be computed before the request
# is sent. The executor still owns the values it applies.
_PROBE_WALL_MS = 60_000


class RunFailure(BaseModel):
    """One test the submission got wrong. Passes are counted; only failures are named."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    name: str
    kind: TestKind
    message: str


class RunResult(BaseModel):
    """`POST /execute`'s answer.

    Fields the grader reads are required rather than defaulted: if the executor ever
    renames `passed`, this must fail loudly instead of quietly reading zero and writing
    evidence that the candidate got nothing right.
    """

    model_config = ConfigDict(extra="ignore", frozen=True)

    outcome: Outcome
    # Bounded, and cross-checked against each other. The executor is hostile-by-assumption
    # and the result travels back on the same stdout the candidate can write to, so a
    # forged marker line reached here as `passed=10000, total=1` and `grade_coding`
    # turned it into a score of 10000.0. The executor now pins `total` to the trusted test
    # count; this is the second half, so the API does not depend on the sandbox having
    # done it.
    passed: NonNegativeInt
    total: NonNegativeInt
    failures: tuple[RunFailure, ...] = ()
    wall_ms: int = 0
    peak_rss_kb: int = 0  # always 0 today — nothing measures it (docs/API.md)
    detail: str = ""

    @model_validator(mode="after")
    def _passed_within_total(self) -> RunResult:
        if self.passed > self.total:
            raise ValueError(f"passed={self.passed} exceeds total={self.total}")
        return self

    @property
    def is_gradeable(self) -> bool:
        return self.outcome == "ok"


class ProbeOutcome(BaseModel):
    """`POST /probe`'s answer — a growth verdict, never a score."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    verdict: Verdict
    slope: float | None = None
    points: tuple[tuple[int, float], ...] = ()
    target: str | None = None
    detail: str = ""

    @property
    def penalises(self) -> bool:
        return self.verdict == "slower_than_target"


class ExecutorUnavailableError(RuntimeError):
    """Unreachable or too slow to answer. docs/API.md's `503` — never a zero."""


class ExecutorProtocolError(RuntimeError):
    """The executor answered something this client cannot read. Our bug, not the service's."""


def execute_payload(
    *,
    source: str,
    entrypoint: str,
    tests: Sequence[Mapping[str, Any]],
    language: Language = "python",
    test_selection: Sequence[str] = (),
    wall_ms: int | None = None,
    memory_mb: int | None = None,
) -> dict[str, Any]:
    """The `/execute` request body. Pure, so the contract test can validate it directly
    against `executor.protocol.ExecuteRequest` without a running service."""
    body: dict[str, Any] = {
        "language": language,
        "source": source,
        "entrypoint": entrypoint,
        "tests": list(tests),
        "test_selection": list(test_selection),
    }
    if wall_ms is not None:
        body["wall_ms"] = wall_ms
    if memory_mb is not None:
        body["memory_mb"] = memory_mb
    return body


def probe_payload(
    *,
    source: str,
    entrypoint: str,
    generator: str,
    sizes: Sequence[int],
    target: str | None,
    language: Language = "python",
    repeats: int = 5,
    wall_ms: int | None = None,
    memory_mb: int | None = None,
) -> dict[str, Any]:
    """The `/probe` request body. Pure, for the same reason as `execute_payload`."""
    body: dict[str, Any] = {
        "language": language,
        "source": source,
        "entrypoint": entrypoint,
        "generator": generator,
        "sizes": list(sizes),
        "target": target,
        "repeats": repeats,
    }
    if wall_ms is not None:
        body["wall_ms"] = wall_ms
    if memory_mb is not None:
        body["memory_mb"] = memory_mb
    return body


class CodeRunner(Protocol):
    """What a grader needs from the executor, and nothing else.

    A Protocol rather than the concrete client so grading can be unit-tested against a
    stub without Docker, and so nothing in the grading path can reach for a method that
    is not on this list.
    """

    def run_tests(
        self,
        *,
        source: str,
        entrypoint: str,
        tests: Sequence[Mapping[str, Any]],
        language: Language = "python",
        test_selection: Sequence[str] = (),
        wall_ms: int | None = None,
        memory_mb: int | None = None,
    ) -> RunResult: ...

    def probe(
        self,
        *,
        source: str,
        entrypoint: str,
        generator: str,
        sizes: Sequence[int],
        target: str | None,
        language: Language = "python",
        repeats: int = 5,
        wall_ms: int | None = None,
        memory_mb: int | None = None,
    ) -> ProbeOutcome: ...


class ExecutorClient:
    """Sync, matching the rest of `apps/api` (sync psycopg, sync routes).

    `http` is injectable so tests can hand in a `TestClient` wrapping the real executor
    app: the sandbox-marked grading tests then exercise the actual endpoint and the actual
    container, in-process, without a second server to start and tear down.
    """

    def __init__(self, base_url: str | None = None, http: httpx.Client | None = None) -> None:
        settings = get_settings()
        self._http = http or httpx.Client(base_url=base_url or settings.executor_url)
        # An injected client owns its own transport policy — `TestClient` rejects a
        # per-request timeout outright — so only a client this object created gets one.
        self._owns_transport = http is None
        self._wall_ms = settings.executor_wall_ms
        self._memory_mb = settings.executor_memory_mb

    def run_tests(
        self,
        *,
        source: str,
        entrypoint: str,
        tests: Sequence[Mapping[str, Any]],
        language: Language = "python",
        test_selection: Sequence[str] = (),
        wall_ms: int | None = None,
        memory_mb: int | None = None,
    ) -> RunResult:
        body = execute_payload(
            source=source,
            entrypoint=entrypoint,
            tests=tests,
            language=language,
            test_selection=test_selection,
            wall_ms=wall_ms or self._wall_ms,
            memory_mb=memory_mb or self._memory_mb,
        )
        return self._post("/execute", body, RunResult, wall_ms or self._wall_ms)

    def probe(
        self,
        *,
        source: str,
        entrypoint: str,
        generator: str,
        sizes: Sequence[int],
        target: str | None,
        language: Language = "python",
        repeats: int = 5,
        wall_ms: int | None = None,
        memory_mb: int | None = None,
    ) -> ProbeOutcome:
        body = probe_payload(
            source=source,
            entrypoint=entrypoint,
            generator=generator,
            sizes=sizes,
            target=target,
            language=language,
            repeats=repeats,
            wall_ms=wall_ms,
            memory_mb=memory_mb,
        )
        return self._post("/probe", body, ProbeOutcome, wall_ms or _PROBE_WALL_MS)

    def _post[T: BaseModel](
        self, path: str, body: dict[str, Any], model: type[T], wall_ms: int
    ) -> T:
        extra: dict[str, Any] = {}
        if self._owns_transport:
            extra["timeout"] = wall_ms / 1000.0 + _TRANSPORT_MARGIN_S
        try:
            response = self._http.post(path, json=body, **extra)
        except httpx.HTTPError as exc:
            raise ExecutorUnavailableError(f"POST {path} failed: {exc}") from exc

        if response.status_code != httpx.codes.OK:
            # A 4xx is this client sending something the contract refuses, which is a bug
            # here; a 5xx is the service failing. Only the second is "unavailable".
            detail = f"POST {path} returned {response.status_code}: {response.text[:300]}"
            if response.status_code >= httpx.codes.INTERNAL_SERVER_ERROR:
                raise ExecutorUnavailableError(detail)
            raise ExecutorProtocolError(detail)

        try:
            return model.model_validate(response.json())
        except ValueError as exc:
            raise ExecutorProtocolError(f"POST {path} returned unreadable body: {exc}") from exc
