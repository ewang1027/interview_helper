"""`api.executor_client` carries its own copy of the executor's wire contract, so this
proves the copy still matches the original.

The duplication is deliberate — see the module docstring on `api.executor_client` — but
duplication without a check is just drift waiting to happen, and the failure mode is
silent: a renamed field would leave the grader reading a defaulted zero and writing
evidence that the candidate got nothing right. These tests are what make the copy safe.
"""

from __future__ import annotations

from typing import get_args

import pytest
from pydantic import ValidationError

from api import executor_client as client
from executor import protocol

TESTS = [{"input": [1, 2], "expected": 3, "name": "adds", "kind": "example", "hidden": True}]
GENERATOR = "def make_input(n):\n    return [list(range(n))]\n"


def test_the_execute_body_this_client_sends_is_accepted_by_the_real_contract():
    """`ExecuteRequest` is `extra='forbid'`, so a field this client invented — or one the
    executor renamed out from under it — fails here rather than at runtime."""
    body = client.execute_payload(
        source="def add(a, b):\n    return a + b\n",
        entrypoint="add",
        tests=TESTS,
        wall_ms=5000,
        memory_mb=256,
    )
    request = protocol.ExecuteRequest.model_validate(body)
    assert request.entrypoint == "add"
    assert request.tests[0].kind == "example"
    assert request.selected() == request.tests


def test_the_probe_body_this_client_sends_is_accepted_by_the_real_contract():
    body = client.probe_payload(
        source="def spans(xs):\n    return xs\n",
        entrypoint="spans",
        generator=GENERATOR,
        sizes=[1000, 2000, 4000],
        target="O(n)",
        repeats=3,
    )
    request = protocol.ProbeRequest.model_validate(body)
    assert request.target == "O(n)"
    assert request.sizes == (1000, 2000, 4000)


def test_the_probe_contract_refuses_too_few_sizes_to_fit():
    """Three points is what the least-squares fit needs. Sending two is a caller bug the
    contract should reject, not something the probe should silently call inconclusive."""
    body = client.probe_payload(
        source="",
        entrypoint="f",
        generator=GENERATOR,
        sizes=[10, 20],
        target="O(n)",
    )
    with pytest.raises(ValidationError):
        protocol.ProbeRequest.model_validate(body)


def test_a_real_execute_response_parses_into_the_client_model():
    response = protocol.ExecuteResponse(
        outcome="ok",
        passed=2,
        total=3,
        failures=(protocol.TestFailure(name="zeros", kind="edge", message="expected 0, got 3"),),
        wall_ms=142,
        detail="",
    )
    parsed = client.RunResult.model_validate(response.model_dump())
    assert (parsed.outcome, parsed.passed, parsed.total) == ("ok", 2, 3)
    assert parsed.failures[0].kind == "edge"
    assert parsed.is_gradeable is response.is_gradeable


def test_a_real_probe_response_parses_into_the_client_model():
    response = protocol.ProbeResponse(
        verdict="slower_than_target",
        slope=2.03,
        points=((2000, 0.01), (4000, 0.04), (8000, 0.16)),
        target="O(n)",
        detail="slope 2.03 exceeds the linear band",
    )
    parsed = client.ProbeOutcome.model_validate(response.model_dump())
    assert parsed.verdict == "slower_than_target"
    assert parsed.penalises is response.penalises
    assert parsed.points[-1] == (8000, 0.16)


def test_both_sides_enumerate_the_same_outcomes_kinds_and_verdicts():
    """The enumerations are the load-bearing part: `outcome` decides whether a run may be
    scored at all, and `verdict` decides whether it may be penalised."""
    assert get_args(client.Outcome) == get_args(protocol.Outcome)
    assert get_args(client.TestKind) == get_args(protocol.TestKind)
    assert get_args(client.Verdict) == get_args(protocol.Verdict)
    assert get_args(client.Language) == get_args(protocol.Language)


def test_no_response_field_exists_on_one_side_only():
    assert set(client.RunResult.model_fields) == set(protocol.ExecuteResponse.model_fields)
    assert set(client.ProbeOutcome.model_fields) == set(protocol.ProbeResponse.model_fields)
    assert set(client.RunFailure.model_fields) == set(protocol.TestFailure.model_fields)
