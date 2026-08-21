"""Test doubles shared by the API's database-backed tests.

Not a conftest fixture: several tests want the class itself, to hand it a canned outcome
per test. Kept in one file because three copies of a `CodeRunner` would be three chances
to drift away from the Protocol the real client implements.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from types import SimpleNamespace
from typing import Any

from api.executor_client import ProbeOutcome, RunFailure, RunResult


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


class ScriptedRunner(FakeRunner):
    """A runner that answers differently per item, for simulating a candidate.

    Selection is by `entrypoint` because that is what identifies an item inside an
    execution request — the executor holds no corpus and never learns an item id.
    """

    def __init__(self, weak_entrypoints: set[str], weak_fraction: float = 0.2) -> None:
        super().__init__()
        self.weak_entrypoints = weak_entrypoints
        self.weak_fraction = weak_fraction
        self.seen: list[str] = []

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
        self.seen.append(entrypoint)
        total = len(tests)
        if entrypoint in self.weak_entrypoints:
            passed = max(0, int(total * self.weak_fraction))
            failures = tuple(
                RunFailure(name=str(case.get("name", "case")), kind="example", message="wrong")
                for case in tests[passed:]
            )
            return RunResult(outcome="ok", passed=passed, total=total, failures=failures)
        return RunResult(outcome="ok", passed=total, total=total)


# --- The model -----------------------------------------------------------------------------


def text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def tool_block(name: str, arguments: dict[str, Any], use_id: str = "tu_1") -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", name=name, input=arguments, id=use_id)


def model_response(
    *blocks: SimpleNamespace, input_tokens: int = 500, output_tokens: int = 60
) -> SimpleNamespace:
    """A `messages.create` response, shaped like the SDK's and no more."""
    return SimpleNamespace(
        content=list(blocks),
        stop_reason="tool_use" if any(b.type == "tool_use" for b in blocks) else "end_turn",
        usage=SimpleNamespace(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        ),
    )


class _ScriptedStream:
    """The context manager `client.messages.stream(...)` returns.

    Chunks the response's text so a delta subscriber sees more than one, which is the only
    way a test can tell streaming from a single write."""

    def __init__(self, response: SimpleNamespace, chunks: int = 3) -> None:
        self._response = response
        text = "".join(b.text for b in response.content if getattr(b, "type", None) == "text")
        size = max(1, -(-len(text) // chunks)) if text else 1
        self._chunks = [text[i : i + size] for i in range(0, len(text), size)]

    def __enter__(self) -> _ScriptedStream:
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    @property
    def text_stream(self) -> Iterator[str]:
        yield from self._chunks

    def get_final_message(self) -> SimpleNamespace:
        return self._response


class ScriptedModel:
    """Answers a fixed sequence of responses, and records what it was asked.

    A script rather than a canned single response, because the thing under test is a
    *loop*: the interesting cases are "asks for a tool, then answers" and "keeps asking".
    Running past the end of the script is an error, not a repeat — a loop that calls one
    more time than the test expected is exactly the bug this catches.

    Serves both `messages.create` and `messages.stream` from the same script, because the
    thing under test should behave the same either way.
    """

    def __init__(self, *responses: SimpleNamespace) -> None:
        self.responses = list(responses)
        self.requests: list[dict[str, Any]] = []
        self.messages = SimpleNamespace(create=self._create, stream=self._stream)

    def _next(self) -> SimpleNamespace:
        if not self.responses:
            raise AssertionError(
                f"the model was called {len(self.requests)} times; the script ran out"
            )
        return self.responses.pop(0)

    def _create(self, **kwargs: Any) -> SimpleNamespace:
        self.requests.append(kwargs)
        return self._next()

    def _stream(self, **kwargs: Any) -> _ScriptedStream:
        self.requests.append(kwargs)
        return _ScriptedStream(self._next())
