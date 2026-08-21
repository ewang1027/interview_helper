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
QUANT = ITEMS["i.quant.0001"]  # exact answer "39"


def context(**kwargs) -> tools.ToolContext:
    return tools.ToolContext(item=kwargs.pop("item", CODING), **kwargs)


def test_the_schemas_are_ordered_and_closed():
    """Order is load-bearing: `tools` renders above `system` in the cached prefix, so a set
    iterated in hash order would invalidate the cache between processes. Closed schemas
    because an unexpected key is a misunderstanding, not an extra."""
    assert [schema["name"] for schema in tools.TOOL_SCHEMAS] == [
        "run_code",
        "reveal_hint",
        "check_answer",
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


# --- check_answer -------------------------------------------------------------------------


def test_check_answer_names_no_item_and_reads_the_one_in_play():
    """docs/API.md specifies `{ item_id, submitted }`, and argues two paragraphs later that
    `reveal_hint` takes no item id because naming one would be a way to read ahead. The same
    argument applies here; the signature had not caught up."""
    schema = next(s for s in tools.TOOL_SCHEMAS if s["name"] == "check_answer")
    assert set(schema["input_schema"]["properties"]) == {"submitted"}

    outcome = tools.dispatch("check_answer", {"submitted": "39 presses"}, context(item=QUANT))
    assert not outcome.is_error
    assert outcome.output["correct"] and outcome.output["method"] == "exact"


def test_check_answer_is_the_same_check_grading_runs():
    """A thin proxy on purpose. An interviewer saying "that is right" and a grader then
    scoring it zero would be two answers to one question, with no way to tell which is
    real."""
    from api.grading import quant

    graded = quant.check_answer(QUANT, "I make it 27.")
    outcome = tools.dispatch("check_answer", {"submitted": "I make it 27."}, context(item=QUANT))
    assert outcome.output["correct"] is graded.correct is False
    assert outcome.output["normalized"] == graded.submitted


def test_check_answer_is_rationed_because_it_is_an_oracle():
    """Ask it about 1, then 2, then 3, and you have the answer without the candidate having
    thought about anything — which is exactly what a model trying to be helpful does."""
    ctx = context(item=QUANT)
    for _ in range(tools.MAX_ANSWER_CHECKS):
        assert not tools.dispatch("check_answer", {"submitted": "40"}, ctx).is_error

    refused = tools.dispatch("check_answer", {"submitted": "41"}, ctx)
    assert refused.is_error
    assert "limit" in refused.output["error"]
    # The refusal says what to do instead: a model told only "no" rephrases and tries again.
    assert "commit to an answer" in refused.output["error"]


def test_a_check_counts_down_out_loud():
    ctx = context(item=QUANT)
    remaining = [
        tools.dispatch("check_answer", {"submitted": "39"}, ctx).output["checks_remaining"]
        for _ in range(tools.MAX_ANSWER_CHECKS)
    ]
    assert remaining == list(range(tools.MAX_ANSWER_CHECKS - 1, -1, -1))


def test_check_answer_on_an_item_with_no_answer_is_an_error_not_a_crash():
    outcome = tools.dispatch("check_answer", {"submitted": "39"}, context(item=CODING))
    assert outcome.is_error and "not graded by an answer" in outcome.output["error"]


def test_an_empty_answer_is_refused_without_spending_a_check():
    ctx = context(item=QUANT)
    assert tools.dispatch("check_answer", {"submitted": "  "}, ctx).is_error
    assert ctx.answer_checks == 0


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


def test_the_surface_is_exactly_four_tools():
    """docs/SECURITY.md: the defence against prompt injection is that succeeding buys very
    little. Anything added here widens what it buys, so the count is pinned — `check_answer`
    joined 2026-08-21 and is the reason it is rationed rather than merely present."""
    assert set(tools.TOOL_NAMES) == {"check_answer", "end_round", "reveal_hint", "run_code"}


def test_a_tool_result_serialises_deterministically():
    """It goes into a model request; unsorted keys are a silent cache invalidator."""
    outcome = tools.ToolOutcome({"b": 1, "a": 2})
    assert outcome.as_text() == '{"a": 2, "b": 1}'
