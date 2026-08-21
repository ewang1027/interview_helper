"""The interviewer's entire capability surface, and what each tool actually does.

docs/API.md lists five tools; four are implemented here and one is deferred with a reason
below. The surface is deliberately small — docs/SECURITY.md's answer to prompt injection is
not filtering, it is that succeeding buys the attacker almost nothing. There is no tool that
writes the corpus, sends anything outbound, reads a secret, or touches mastery, and grading
is not a tool at all, so the interviewer cannot score itself.

Two tools deviate from the signature docs/API.md specifies, both in the same direction —
taking away a parameter that let the model choose what it was measured against:

**`run_code` does not take tests.** docs/API.md's signature has the caller passing
`tests[]`; here the tests come from the corpus item and the model supplies only the source.
Letting the model choose the tests would let it run a payload of its own devising *and*
mark its own work, which are the two things this design spends the most effort preventing.

**`check_answer` does not take an `item_id`** (2026-08-21). docs/API.md specifies
`{ item_id, submitted }`, and argues two paragraphs later that `reveal_hint` takes no item
id because naming a different one would be a way to read ahead. That argument applies here
unchanged and the signature had not caught up: there is exactly one item in play, so the
tool reads it from the context.

**`check_answer` is also the only tool that is an oracle**, and it is capped for it. Ask it
about 1, then 2, then 3, and you have the answer without the candidate having thought about
anything — which is precisely what a model trying to be helpful does, the same failure mode
`reveal_hint`'s monotonic check exists for. `MAX_ANSWER_CHECKS` successful checks per item
per session is enough for a candidate revising a stated answer and nowhere near enough to
search. The count is recovered from the turn record, not held in memory, because a context
is rebuilt every turn and an in-memory counter would cap nothing.

Deferred, and why:

- **`record_observation`** writes `concept_evidence` mid-session. Evidence has exactly one
  producer today — the grader — and adding a second risks double-counting a concept from
  one item.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from api.executor_client import CodeRunner, ExecutorProtocolError, ExecutorUnavailableError
from api.grading.coding import hint_penalty
from api.grading.quant import check_answer
from corpus.models import Item

logger = logging.getLogger(__name__)

# How many times the interviewer may check an answer against one item. An oracle with no
# limit is a way to read the answer off the grader; a candidate revising theirs needs two
# or three. Chosen, not calibrated — the number is here to be raised if real sessions say so.
MAX_ANSWER_CHECKS = 3

# Ordered, and the order is load-bearing: `tools` renders above `system` in the cached
# prefix, so a set iterated in hash order would invalidate the cache between processes.
TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "run_code",
        "description": (
            "Run the candidate's code against this problem's own hidden tests and return "
            "what passed. Use this to check a claim about code rather than reading it. "
            "The tests belong to the problem; you cannot choose or add to them."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "language": {"type": "string", "enum": ["python"]},
                "source": {"type": "string", "description": "The complete program to run."},
            },
            "required": ["language", "source"],
            "additionalProperties": False,
        },
    },
    {
        "name": "reveal_hint",
        "description": (
            "Give the candidate the next hint. Hints are graduated, least to most "
            "revealing, and each one costs the candidate part of their score — the cost "
            "is returned so you can tell them what it cost. Levels are 1-indexed and "
            "must be taken in order."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "level": {"type": "integer", "minimum": 1, "description": "1-indexed hint."}
            },
            "required": ["level"],
            "additionalProperties": False,
        },
    },
    {
        "name": "check_answer",
        "description": (
            "Check the answer the candidate has stated against this problem's own answer. "
            "Pass their answer exactly as they gave it. Use this to find out whether they "
            "are right before deciding what to ask next — not to explore what the answer "
            f"might be: you may check at most {MAX_ANSWER_CHECKS} times on this problem, "
            "and a check is not a hint."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "submitted": {
                    "type": "string",
                    "description": "The candidate's stated answer, in their own words.",
                }
            },
            "required": ["submitted"],
            "additionalProperties": False,
        },
    },
    {
        "name": "end_round",
        "description": (
            "Finish with this problem — solved, abandoned, or out of time. Say why in one "
            "line. The application decides what happens next; you do not move on yourself."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"reason": {"type": "string"}},
            "required": ["reason"],
            "additionalProperties": False,
        },
    },
]

TOOL_NAMES = frozenset(schema["name"] for schema in TOOL_SCHEMAS)


@dataclass
class ToolContext:
    """What the tools are allowed to act on: one item, one runner, and the hints already
    taken. Not a session and not a database handle — a tool that cannot reach the database
    cannot write evidence, which is the point."""

    item: Item
    runner: CodeRunner | None = None
    hints_revealed: int = 0
    answer_checks: int = 0
    ended: bool = False
    end_reason: str | None = None
    hints_taken: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class ToolOutcome:
    """A tool's result as the model will see it, plus whether it was an error.

    `is_error` is not decoration: a tool result the model cannot tell failed produces a
    confident interviewer acting on nothing."""

    output: dict[str, Any]
    is_error: bool = False

    def as_text(self) -> str:
        return json.dumps(self.output, sort_keys=True)


def dispatch(name: str, arguments: dict[str, Any], context: ToolContext) -> ToolOutcome:
    """Run one tool call. Never raises: a tool that throws would abort a turn the candidate
    is in the middle of, and an error the model can read is recoverable."""
    try:
        if name == "run_code":
            return _run_code(arguments, context)
        if name == "reveal_hint":
            return _reveal_hint(arguments, context)
        if name == "check_answer":
            return _check_answer(arguments, context)
        if name == "end_round":
            return _end_round(arguments, context)
    except Exception as exc:  # pragma: no cover - the guard, not a path
        logger.exception("tool %s failed", name)
        return ToolOutcome({"error": f"{type(exc).__name__}: {exc}"}, is_error=True)
    return ToolOutcome({"error": f"No such tool: {name!r}."}, is_error=True)


def _run_code(arguments: dict[str, Any], context: ToolContext) -> ToolOutcome:
    grading = context.item.grading or {}
    if grading.get("type") != "tests":
        return ToolOutcome({"error": f"{context.item.id} has no runnable tests."}, is_error=True)
    if context.runner is None:  # pragma: no cover - wiring error, not a model error
        return ToolOutcome({"error": "No executor is available."}, is_error=True)

    language = arguments.get("language", "python")
    if language not in (grading.get("languages") or []):
        return ToolOutcome(
            {"error": f"{language!r} is not one of this problem's languages."}, is_error=True
        )
    limits = grading.get("limits") or {}
    try:
        result = context.runner.run_tests(
            language=language,
            source=str(arguments.get("source", "")),
            entrypoint=grading["entrypoint"],
            tests=grading["tests"],
            wall_ms=limits.get("wall_ms"),
            memory_mb=limits.get("memory_mb"),
        )
    except ExecutorUnavailableError as exc:
        return ToolOutcome({"error": f"The code runner is unavailable: {exc}"}, is_error=True)
    except ExecutorProtocolError as exc:
        return ToolOutcome({"error": f"The code runner refused this: {exc}"}, is_error=True)

    # Passes are a count; only failures are enumerated (docs/API.md). Handing the model
    # every passing case would spend context on the part that carries no information.
    return ToolOutcome(
        {
            "outcome": result.outcome,
            "passed": result.passed,
            "total": result.total,
            "failures": [failure.model_dump() for failure in result.failures[:3]],
            "detail": result.detail,
            "gradeable": result.is_gradeable,
        }
    )


def _reveal_hint(arguments: dict[str, Any], context: ToolContext) -> ToolOutcome:
    hints = context.item.hints
    if not hints:
        return ToolOutcome({"error": "This problem has no hints."}, is_error=True)
    try:
        level = int(arguments.get("level", 0))
    except (TypeError, ValueError):
        return ToolOutcome({"error": "level must be an integer."}, is_error=True)
    if not 1 <= level <= len(hints):
        return ToolOutcome(
            {"error": f"Hint levels for this problem are 1 to {len(hints)}."}, is_error=True
        )
    if level > context.hints_revealed + 1:
        # Monotonic by contract (docs/API.md): level N implies N-1 was given. Enforced
        # rather than trusted, because skipping to the last hint is exactly what a model
        # trying to be helpful does, and it is the most expensive one.
        return ToolOutcome(
            {"error": f"Hints are taken in order; the next one is {context.hints_revealed + 1}."},
            is_error=True,
        )
    context.hints_revealed = max(context.hints_revealed, level)
    context.hints_taken.append(level)
    return ToolOutcome(
        {
            "level": level,
            "text": hints[level - 1],
            "score_penalty": round(hint_penalty(level), 4),
            "hints_remaining": len(hints) - level,
        }
    )


def _check_answer(arguments: dict[str, Any], context: ToolContext) -> ToolOutcome:
    """The same check grading runs, offered mid-interview and rationed.

    A thin proxy onto `api.grading.quant.check_answer` on purpose: an interviewer told "that
    is right" during the round and a grader that then scores it zero would be two different
    answers to one question, and the candidate would have no way to tell which was real.
    """
    grading = context.item.grading or {}
    if grading.get("type") != "answer":
        return ToolOutcome(
            {"error": f"{context.item.id} is not graded by an answer."}, is_error=True
        )
    submitted = str(arguments.get("submitted", "")).strip()
    if not submitted:
        return ToolOutcome(
            {"error": "submitted must be the answer the candidate stated."}, is_error=True
        )
    if context.answer_checks >= MAX_ANSWER_CHECKS:
        # The refusal says what to do instead, because a model that is only told "no" tends
        # to rephrase and try again.
        return ToolOutcome(
            {
                "error": (
                    f"You have already checked {context.answer_checks} answers on this "
                    "problem, which is the limit. Ask the candidate to commit to an answer "
                    "and reason about it with them instead."
                )
            },
            is_error=True,
        )

    context.answer_checks += 1
    checked = check_answer(context.item, submitted)
    return ToolOutcome(
        {
            "correct": checked.correct,
            "normalized": checked.submitted,
            "method": checked.method,
            "checks_remaining": MAX_ANSWER_CHECKS - context.answer_checks,
        }
    )


def _end_round(arguments: dict[str, Any], context: ToolContext) -> ToolOutcome:
    context.ended = True
    context.end_reason = str(arguments.get("reason", "")).strip() or "no reason given"
    return ToolOutcome({"ok": True, "reason": context.end_reason})
