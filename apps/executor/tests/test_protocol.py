"""Contract tests for the execute protocol. No sandbox involved."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from executor.protocol import ExecuteRequest, ExecuteResponse


def test_only_an_ok_outcome_is_gradeable():
    """docs/GRADING.md: a crashed or timed-out run is a failed grading, not a zero.

    The distinction matters because a zero writes evidence of weakness against a
    concept the candidate may know perfectly well.
    """
    assert ExecuteResponse(outcome="ok", passed=3, total=3).is_gradeable
    for bad in ("timeout", "out_of_memory", "pid_limit", "compile_error", "harness_error"):
        assert not ExecuteResponse(outcome=bad).is_gradeable


def test_request_rejects_unknown_fields():
    """extra="forbid" — a typo'd field must not be silently dropped, since a dropped
    limit would mean running untrusted code with no cap."""
    with pytest.raises(ValidationError):
        ExecuteRequest(language="python", source="", tests="", wall_millis=100)


def test_request_rejects_nonpositive_limits():
    with pytest.raises(ValidationError):
        ExecuteRequest(language="python", source="", tests="", wall_ms=0)
    with pytest.raises(ValidationError):
        ExecuteRequest(language="python", source="", tests="", memory_mb=-1)


def test_unknown_language_is_rejected():
    with pytest.raises(ValidationError):
        ExecuteRequest(language="ruby", source="", tests="")
