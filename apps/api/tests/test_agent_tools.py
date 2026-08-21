"""The interviewer's tools, without a model or a database.

The interesting cases are the refusals. A tool that does its job is one line; a tool that
lets the model skip to the most expensive hint, or run code against tests of its own
choosing, is the reason this surface is small.
"""

from __future__ import annotations

import json

import pytest
from fakes import FakeRunner

from api.agent import tools
from api.executor_client import ExecutorUnavailableError, RunResult
from corpus.loader import load_items

ITEMS = {item.id: item for item in load_items()}
CODING = ITEMS["i.code.0001"]
BEHAVIORAL = ITEMS["i.behav.0001"]


def context(**kwargs) -> tools.ToolContext:
    return tools.ToolContext(item=kwargs.pop("item", CODING), **kwargs)


def test_the_schemas_are_ordered_and_closed():
    """Order is load-bearing: `tools` renders above `system` in the cached prefix, so a set
    iterated in hash order would invalidate the cache between processes. Closed schemas
    because an unexpected key is a misunderstanding, not an extra."""
    assert [schema["name"] for schema in tools.TOOL_SCHEMAS] == [
        "run_code",
        "reveal_hint",
        "end_round",
    ]
    for schema in tools.TOOL_SCHEMAS:
        assert schema["input_schema"]["additionalProperties"] is False
        assert schema["input_schema"]["required"]
        assert schema["description"].strip()


def test_run_code_uses_the_items_own_tests():
    """docs/API.md's signature has the caller passing tests; here the corpus owns them.
    A model that chooses its own tests marks its own work."""
    runner = FakeRunner(RunResult(outcome="ok", passed=0, total=0))
    outcome = tools.dispatch(
        "run_code", {"language": "python", "source": "def f(): pass"}, context(runner=runner)
    )
    assert not outcome.is_error
    assert outcome.output["total"] == len(CODING.grading["tests"])
    assert outcome.output["gradeable"] is True
    assert "run_code" not in json.dumps(tools.TOOL_SCHEMAS[0]["input_schema"]["properties"])
    assert "tests" not in tools.TOOL_SCHEMAS[0]["input_schema"]["properties"]


def test_run_code_refuses_a_language_the_item_does_not_declare():
    outcome = tools.dispatch(
        "run_code", {"language": "cpp", "source": "int main(){}"}, context(runner=FakeRunner())
    )
    assert outcome.is_error
    assert "languages" in outcome.output["error"]


def test_run_code_on_an_item_with_no_tests_is_an_error_not_a_crash():
    outcome = tools.dispatch(
        "run_code",
        {"language": "python", "source": "x"},
        context(item=BEHAVIORAL, runner=FakeRunner()),
    )
    assert outcome.is_error
    assert "no runnable tests" in outcome.output["error"]


def test_an_unavailable_executor_is_reported_to_the_model_not_raised():
    """A tool that throws aborts a turn the candidate is in the middle of. An error the
    model can read lets it say so and carry on."""

    class Broken(FakeRunner):
        def run_tests(self, **kwargs):
            raise ExecutorUnavailableError("connection refused")

    outcome = tools.dispatch(
        "run_code", {"language": "python", "source": "x"}, context(runner=Broken())
    )
    assert outcome.is_error
    assert "unavailable" in outcome.output["error"]


def test_hints_are_monotonic():
    """Level N implies N-1 was given (docs/API.md). Enforced rather than trusted: skipping
    to the last hint is what a model trying to be helpful does, and it is the dearest one."""
    ctx = context()
    skipped = tools.dispatch("reveal_hint", {"level": 3}, ctx)
    assert skipped.is_error
    assert ctx.hints_revealed == 0

    first = tools.dispatch("reveal_hint", {"level": 1}, ctx)
    assert not first.is_error
    assert first.output["text"] == CODING.hints[0]
    assert first.output["score_penalty"] == pytest.approx(0.05)
    assert ctx.hints_revealed == 1

    second = tools.dispatch("reveal_hint", {"level": 2}, ctx)
    assert second.output["score_penalty"] == pytest.approx(0.10)
    assert ctx.hints_taken == [1, 2]


def test_re_reading_a_hint_already_given_is_allowed():
    """Not a new cost — the candidate has already paid for it, and refusing would make the
    interviewer unable to repeat itself."""
    ctx = context()
    tools.dispatch("reveal_hint", {"level": 1}, ctx)
    again = tools.dispatch("reveal_hint", {"level": 1}, ctx)
    assert not again.is_error
    assert ctx.hints_revealed == 1


@pytest.mark.parametrize("level", [0, -1, 99, "two"])
def test_a_nonsense_hint_level_is_refused(level):
    outcome = tools.dispatch("reveal_hint", {"level": level}, context())
    assert outcome.is_error


def test_end_round_records_a_reason():
    ctx = context()
    outcome = tools.dispatch("end_round", {"reason": "solved with two hints"}, ctx)
    assert outcome.output == {"ok": True, "reason": "solved with two hints"}
    assert ctx.ended is True
    assert ctx.end_reason == "solved with two hints"


def test_end_round_without_a_reason_still_ends():
    ctx = context()
    tools.dispatch("end_round", {}, ctx)
    assert ctx.ended is True
    assert ctx.end_reason == "no reason given"


def test_a_tool_that_does_not_exist_is_an_error_the_model_can_read():
    outcome = tools.dispatch("delete_the_corpus", {}, context())
    assert outcome.is_error
    assert "No such tool" in outcome.output["error"]


def test_the_surface_is_exactly_three_tools():
    """docs/SECURITY.md: the defence against prompt injection is that succeeding buys very
    little. Anything added here widens what it buys, so the count is pinned."""
    assert set(tools.TOOL_NAMES) == {"end_round", "reveal_hint", "run_code"}


def test_a_tool_result_serialises_deterministically():
    """It goes into a model request; unsorted keys are a silent cache invalidator."""
    outcome = tools.ToolOutcome({"b": 1, "a": 2})
    assert outcome.as_text() == '{"a": 2, "b": 1}'
