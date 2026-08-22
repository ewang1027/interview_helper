"""The quant grader: a deterministic answer check, and the derivation judged beside it.

docs/GRADING.md has asked for both halves since Phase 0, and says why neither is enough
alone: the number is the point of the exercise, but **a correct number with wrong reasoning
is not a pass in a quant interview** — a memorised value and a derived one are
indistinguishable from the value alone. So the answer is checked symbolically and the
derivation is judged against the item's `reasoning_rubric`, by the same code that grades a
system-design answer.

Four decisions shape what the numbers mean:

1. **The answer is read from the candidate's closing statement, not from the whole page.**
   A derivation mentions numbers that are not the answer — a sanity bound, a wrong first
   guess, the naive value the problem exists to refute. Scanning everything would accept
   `27` as evidence for an answer of `39`; taking only the last token would reject "39
   presses, which must exceed 27" for the same reason. What is read is the line the
   candidate declared their answer on, or failing that the last line that contains
   arithmetic at all.

2. **A stated answer and no answer are different.** A candidate who never committed to a
   number has not got it wrong — they have not answered. That scores zero on the answer
   half and writes **no evidence**, on the same reasoning that makes a not-demonstrated
   rubric criterion silent: mastery is derived from evidence, so recording silence as
   failure would compound a lie through every later plan.

3. **The answer cannot carry a pass on its own.** It is worth `ANSWER_WEIGHT` of the grade
   and the derivation the rest, so a bare correct number tops out at 0.4 — which is what
   docs/GRADING.md means by "not a pass". The reverse is deliberate too: a sound derivation
   with a slipped digit keeps most of what the reasoning earned, because that is how a real
   interviewer scores it, and the rubric's own arithmetic criterion already docks it.

4. **sympy parses untrusted text, so it is walled first.** The submission is whatever the
   candidate typed, and `parse_expr` evaluates what it parses. Every expression that
   reaches it has passed a character allowlist, a length cap, an exponent bound and a node
   budget, and is evaluated with builtins removed. docs/SECURITY.md's rule that the wall
   comes before the work, not after it, is the lesson the complexity probe learned the
   expensive way.

Pure and database-free, like every grader here: it returns rows, and the session layer
writes them.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from itertools import islice
from typing import Any

import sympy
from sympy.parsing.sympy_parser import convert_xor, parse_expr, standard_transformations

from api.grading.coding import Evidence, hint_retention
from api.grading.rubric import (
    Judgement,
    criteria_detail,
    evidence_from,
    judge_criteria,
    weighted_score,
)
from api.settings import Settings
from corpus.models import Item

logger = logging.getLogger(__name__)

GRADER_VERSION = "quant.answer@1"

# What the number is worth. Below half on purpose: docs/GRADING.md asks that a correct
# answer with wrong reasoning not be a pass, and this is the arithmetic that says so.
# The derivation carries the rest.
ANSWER_WEIGHT = 0.4

# A symbolic equivalence is a fact, not an opinion — the same standing as a hidden test
# passing, and the same confidence the coding grader gives one.
DECLARED_CONFIDENCE = 0.9

# ... but only when the candidate said which expression was their answer. Read out of a
# closing sentence instead, the check is still deterministic while *what it was pointed at*
# was inferred, and a mis-read is a wrong verdict about a right answer. The claim is
# softened rather than dropped, the same way the coding grader softens a weakness claim
# built on an adversarial case.
INFERRED_CONFIDENCE = 0.75

# How far back to look for a closing statement when nothing was declared. A candidate who
# ends on "hope that's right" should not lose the line above it; one whose answer is twenty
# lines up did not state an answer.
CLOSING_LINES = 5

# --- The wall around the parser -----------------------------------------------------------

# No `!`, no `[`, no `,` — factorials, subscripts and tuples are not answer forms, and each
# is a way to ask sympy for unbounded work or an unexpected type.
ALLOWED_CHARS = re.compile(r"^[0-9A-Za-z_+\-*/^().\s]+$")
MAX_EXPR_CHARS = 120
# Bounds the tree `parse_expr` may hand back. Reached only by input that already passed the
# character and exponent checks, so it is the last line rather than the first.
MAX_NODES = 400
# `9**9**9` is seven characters, passes every other check, and does not finish.
MAX_EXPONENT = 64
# At most this many expressions are pulled out of one closing statement, so a line of prose
# full of figures cannot turn one grading into a hundred simplifications.
MAX_CANDIDATES = 12

# `^` means exponentiation to everyone writing an answer and XOR to Python, which is what
# `parse_expr` reads without this.
TRANSFORMATIONS = (*standard_transformations, convert_xor)

# Names an answer may use. Everything else parses to a free symbol, which is harmless and
# simply will not match. `__builtins__` is emptied explicitly: `eval` reinstates the real
# ones when globals arrive without them, which is the opposite of what an allowlist means.
#
# The four constructors are not optional. `parse_expr` rewrites the source it was handed —
# `39` becomes `Integer(39)`, a name becomes `Symbol(...)` — and resolves those against
# these globals, so an allowlist without them refuses every expression, including `1/3`.
# It did, in the first draft, and the smoke run is the only reason that was noticed: every
# case still passed through `accept_forms`, so the sympy path looked like it worked.
SAFE_NAMES: dict[str, Any] = {
    "__builtins__": {},
    "Integer": sympy.Integer,
    "Float": sympy.Float,
    "Rational": sympy.Rational,
    "Symbol": sympy.Symbol,
    "sqrt": sympy.sqrt,
    "exp": sympy.exp,
    "log": sympy.log,
    "ln": sympy.log,
    "pi": sympy.pi,
    "E": sympy.E,
    "Abs": sympy.Abs,
}

# A decimal is accepted as a rounding of the target only if it carries this many
# significant figures. Otherwise "5" is a correct rounding of 5.333 and of nothing useful.
MIN_SIGNIFICANT = 3

_THOUSANDS = re.compile(r"(?<=\d),(?=\d\d\d(?!\d))")
_EXPONENT = re.compile(r"(?:\*\*|\^)\s*\(?\s*([^\s()]+)")
# `\d[\d,]*` swallowed a trailing comma, so "Answer: 39, which must exceed 27" extracted
# the span `39,` — which `ALLOWED_CHARS` then refuses, because a comma is not an allowed
# character. A correct answer scored 0.0 at the system's *highest* confidence, writing
# evidence of a weakness the candidate had just disproved. Only thousands separators are
# part of a number; a comma in any other position ends the term.
_TERM = (
    r"(?:[A-Za-z_]\w*\s*\([^()\n]{0,40}\)|\(\s*[^()\n]{0,40}\s*\)"
    r"|\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
)
_OP = r"(?:\*\*|[-+*/^])"
_EXPR = re.compile(rf"(?<![\w.]){_TERM}(?:\s*{_OP}\s*{_TERM})*")
_DECIMAL = re.compile(r"^[-+]?(?:\d+\.\d+|\d+|\.\d+)$")
_MARKER = re.compile(r"\b(?:final\s+answer|answer)\b\s*(?:is\b)?\s*[:=]?\s*(?P<rest>.*)$", re.I)


@dataclass(frozen=True)
class AnswerCheck:
    """What the candidate claimed, and whether it is right.

    `stated` and `correct` are separate questions. A candidate who never committed to a
    number is not wrong, and the difference decides whether any evidence is written at all.
    """

    stated: bool
    correct: bool
    declared: bool
    submitted: str | None
    method: str
    detail: str

    @property
    def confidence(self) -> float:
        return DECLARED_CONFIDENCE if self.declared else INFERRED_CONFIDENCE

    def as_dict(self) -> dict[str, Any]:
        return {
            "stated": self.stated,
            "correct": self.correct,
            "declared": self.declared,
            "submitted": self.submitted,
            "method": self.method,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class QuantGrade:
    """The whole result: the number, the derivation, and what both are evidence of."""

    status: str
    item_id: str
    score: float | None
    hints_revealed: int
    answer: AnswerCheck
    judgements: tuple[Judgement, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    summary: str = ""
    detail: str = ""
    grader_version: str = GRADER_VERSION
    components: dict[str, float] = field(default_factory=dict)

    def as_detail(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "score": self.score,
            "hints_revealed": self.hints_revealed,
            "answer": self.answer.as_dict(),
            "criteria": [j.as_dict() for j in self.judgements],
            "not_demonstrated": [j.id for j in self.judgements if not j.demonstrated],
            "components": self.components,
            "summary": self.summary,
            "detail": self.detail,
        }


# --- Reading the answer out of a derivation ------------------------------------------------


def expressions(text: str) -> list[str]:
    """Every arithmetic-looking span in one line, in the order written.

    All of them, not just the last: "16/3 changeovers, about 5.33" states the answer twice
    and the first spelling is the exact one. Requiring the last would fail a candidate for
    adding a decimal, and requiring the first would fail one for showing their working."""
    return [match.group(0).strip() for match in islice(_EXPR.finditer(text), MAX_CANDIDATES)]


def closing_statement(answer: str) -> tuple[str, bool]:
    """The span the answer is read from, and whether the candidate declared it as one.

    A declaration wins wherever it appears — "Answer: 39" is unambiguous in a way no
    heuristic improves on. Without one, the last line carrying arithmetic is the
    conclusion, which is where a derivation puts it.
    """
    lines = [line.strip() for line in answer.splitlines() if line.strip()]
    # Where the working ends. A marker *above* this is not a declaration of the answer —
    # it is a retrospective mention inside the derivation, and "the naive answer is 27" is
    # the natural way to write the sentence every item whose trap is 27 needs to write.
    # Measured before this bound existed: a derivation reaching the right answer on its
    # last line scored 0.0 at the highest confidence in the system, because `answer is` on
    # line two outranked `So E0 = 39 presses` on line four.
    last_arithmetic = max(
        (index for index, line in enumerate(lines) if expressions(line)), default=-1
    )
    for index in range(len(lines) - 1, -1, -1):
        if index < last_arithmetic:
            break
        marked = _MARKER.search(lines[index])
        # A marker only counts if something arithmetic follows it: "I will answer in
        # dollars" names no number and is not a declaration.
        if marked and expressions(marked.group("rest")):
            return marked.group("rest").strip(), True
    for line in reversed(lines[-CLOSING_LINES:]):
        if expressions(line):
            return line, False
    return "", False


# --- Parsing it safely ---------------------------------------------------------------------


def safe_parse(text: str) -> sympy.Expr | None:
    """Parse one expression, or refuse. Never raises, and never runs unbounded work.

    `parse_expr` compiles and evaluates what it is given, and what it is given here was
    typed by the candidate. The order matters: every bound is checked *before* the parse
    that would be expensive, because a budget enforced after the work is not a budget —
    the same correction the complexity probe's driver needed.
    """
    expression = _THOUSANDS.sub("", text.strip())
    if not expression or len(expression) > MAX_EXPR_CHARS:
        return None
    if not ALLOWED_CHARS.match(expression):
        return None
    # An answer form needs at most one exponent. More than one is a tower, and the
    # per-token bound below cannot see it: `_EXPONENT`'s `[^\s()]+` stops at a paren, so
    # `(2)**(63)**(63)` presented two exponents of 63 — both under the limit — while
    # meaning `2**(63**63)`. `MAX_NODES` is checked *after* the parse, so it never ran.
    # Measured: fifteen characters, extracted from an ordinary closing statement, and
    # `parse_expr` had not returned after ninety seconds. That hangs the worker inside the
    # API process, leaves the item in `grading` forever, and a retry is refused 409 —
    # exactly the failure docs/GRADING.md's "failure is a failure" section exists to stop.
    if len(_EXPONENT.findall(expression)) > 1:
        return None
    for exponent in _EXPONENT.findall(expression):
        # Numeric exponents only, and small ones. A symbolic or towering exponent is not an
        # answer form, and both are ways to ask for arbitrary work.
        try:
            if abs(float(exponent)) > MAX_EXPONENT:
                return None
        except ValueError:
            return None
    try:
        parsed = parse_expr(
            expression,
            global_dict=dict(SAFE_NAMES),
            local_dict={},
            transformations=TRANSFORMATIONS,
        )
    except Exception:
        # A parser fed prose fails in a dozen ways, none of which is a grading failure: an
        # unparseable span is simply not the answer.
        logger.debug("not an expression: %r", expression[:60])
        return None
    if not isinstance(parsed, sympy.Expr):
        return None
    # Counted lazily and stopped at the cap: a tree big enough to matter is refused without
    # ever being walked to the end.
    if len(list(islice(sympy.preorder_traversal(parsed), MAX_NODES + 1))) > MAX_NODES:
        return None
    return parsed


def equivalent(candidate: sympy.Expr, target: sympy.Expr) -> bool:
    """Whether two expressions are the same number, however each was spelled.

    This is what makes `1/3`, `0.333...` and `2/6` one answer rather than three."""
    try:
        return bool(sympy.simplify(candidate - target).is_zero)
    except Exception:
        # An undecidable difference is a non-match, not a crash.
        return False


def rounds_to(text: str, target: float) -> bool:
    """Whether a decimal is the target, correctly rounded to the precision it was written to.

    This is how a person reads "5.33" against 16/3, and refusing it would write evidence of
    a weakness the candidate does not have — the failure mode this grader is most able to
    cause. The significant-figure floor is what stops it from also accepting "5".
    """
    written = text.strip().replace(" ", "")
    if not _DECIMAL.match(written):
        return False
    if len(written.lstrip("+-").replace(".", "").lstrip("0")) < MIN_SIGNIFICANT:
        return False
    places = len(written.split(".")[1]) if "." in written else 0
    try:
        return round(target, places) == float(written)
    except (ValueError, OverflowError):
        return False


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def accepted_form(statement: str, forms: list[str]) -> str | None:
    """An `accept_forms` entry appearing in the closing statement, if one does.

    These exist for answers sympy cannot normalise — a mixed number, a currency figure —
    so they are matched as text rather than parsed. Guarded on both sides so `39` does not
    match inside `390` or `39.5` — but only against *digits*: a form at the end of a
    sentence is followed by a full stop, and a guard that refuses that refuses most of the
    real ones.

    **A form the parser can already handle is skipped**, because it is not what this list is
    for and matching it as text is strictly worse. `i.quant.0006`'s answer is `1`, and `1`
    listed as an accepted form matched the numerator of "about 1/9 of them, so 0.111" — a
    wrong answer marked correct. Anything parseable is already decided, correctly, by the
    equivalence check above; what is left here is exactly the forms that check cannot read.
    """
    haystack = _normalise(statement)
    for form in forms:
        needle = _normalise(form)
        if not needle or safe_parse(form) is not None:
            continue
        if re.search(rf"(?<!\d)(?<!\d\.){re.escape(needle)}(?!\d)(?!\.\d)", haystack):
            return form
    return None


def check_answer(item: Item, submission: str) -> AnswerCheck:
    """Read the candidate's answer out of their working, and decide whether it is right."""
    grading = item.grading or {}
    expected = grading.get("answer") or {}
    forms = list(grading.get("accept_forms") or [])
    statement, declared = closing_statement(submission)
    if not statement:
        return AnswerCheck(
            stated=False,
            correct=False,
            declared=False,
            submitted=None,
            method="none",
            detail="no answer was stated",
        )

    def verdict(correct: bool, method: str, submitted: str, detail: str) -> AnswerCheck:
        return AnswerCheck(
            stated=True,
            correct=correct,
            declared=declared,
            submitted=submitted,
            method=method,
            detail=detail,
        )

    candidates = expressions(statement)
    if declared and candidates:
        # A declaration is a commitment, so it is graded on the number that was declared —
        # the first span after the marker — and not on any of the twelve the rest of the
        # sentence happens to contain. `expressions` splits on non-operator words, so
        # "Final answer: 0, since with 1 in 9 chance per guest it rounds to 0" yielded the
        # separate candidates 0, 1 and 9, and the loop below accepted whichever matched:
        # a candidate who declared the wrong number scored 1.0 at 0.9 confidence because
        # the right one appeared later in their own sentence. It also handed out a free
        # hedge — "Answer: 30 or 31 or ... or 39" was twelve guesses for the price of one.
        #
        # The undeclared path deliberately keeps all of them. It carries
        # INFERRED_CONFIDENCE rather than DECLARED_CONFIDENCE precisely because it is
        # reading a conclusion out of prose, and "16/3 changeovers, about 5.33" states one
        # answer twice — requiring the first there would fail a candidate for adding a
        # decimal.
        candidates = candidates[:1]
    exact = expected.get("exact")
    target = safe_parse(str(exact)) if exact is not None else None
    numeric = expected.get("numeric")
    tolerance = float(expected.get("tolerance", 1e-6))

    for candidate in candidates:
        # Rounding is judged on what was written, not on what it parsed to: the precision a
        # candidate chose is a property of the text and is lost the moment it becomes a float.
        if numeric is not None and rounds_to(candidate, float(numeric)):
            return verdict(True, "rounded", candidate, f"{candidate} is {numeric} rounded")
        parsed = safe_parse(candidate)
        if parsed is None:
            continue
        if target is not None and equivalent(parsed, target):
            return verdict(True, "exact", candidate, f"{candidate} is equivalent to {exact}")
        if numeric is None or parsed.free_symbols:
            continue
        try:
            value = float(parsed.evalf())
        except (TypeError, ValueError):
            continue
        if abs(value - float(numeric)) <= tolerance:
            return verdict(True, "numeric", candidate, f"{candidate} is within {tolerance}")

    # Last, and deliberately: an accepted form is a substring match on a sentence, which is
    # a weaker thing to be right about than an equivalence sympy proved. Trying it first
    # would hide a broken parser behind a list the corpus author wrote by hand.
    matched = accepted_form(statement, forms)
    if matched is not None:
        return verdict(True, "accept_form", matched, f"matched the accepted form {matched!r}")

    submitted = candidates[0] if candidates else statement
    return verdict(False, "mismatch", submitted, f"{submitted} is not {exact or numeric}")


# --- The grader ----------------------------------------------------------------------------


def grade_quant(
    item: Item,
    submission: str,
    *,
    hints_revealed: int = 0,
    session_id: str | None = None,
    client: Any = None,
    settings: Settings | None = None,
) -> QuantGrade:
    """Grade one quant submission: the number checked, the derivation judged."""
    grading = item.grading or {}
    if grading.get("type") != "answer":
        raise ValueError(f"{item.id} is not graded by answer (type={grading.get('type')!r})")
    expected = grading.get("answer") or {}
    if expected.get("exact") is None and expected.get("numeric") is None:
        # The validator errors on this shape, so it should never reach here — and if it
        # does, every submission is "wrong" against nothing. A failed grading with a reason
        # is visible; a confident zero corrupts mastery permanently (docs/GRADING.md).
        raise ValueError(f"{item.id} has no `exact` or `numeric` answer to check against")
    if not submission.strip():
        raise ValueError("an empty answer cannot be graded")

    answer = check_answer(item, submission)
    answer_score = 1.0 if answer.correct else 0.0

    criteria = list(grading.get("reasoning_rubric") or [])
    judgements: tuple[Judgement, ...] = ()
    summary = ""
    if criteria:
        judgements, summary = judge_criteria(
            item, submission, criteria, session_id=session_id, client=client, settings=settings
        )
        reasoning = weighted_score(judgements)
        raw = ANSWER_WEIGHT * answer_score + (1.0 - ANSWER_WEIGHT) * reasoning
        components = {"answer": answer_score, "reasoning": round(reasoning, 4)}
        detail = f"answer {'correct' if answer.correct else answer.detail}; "
        detail += criteria_detail(judgements)
    else:
        # An item that asks only for a number is graded only on the number. The schema
        # makes `reasoning_rubric` optional, and inventing a missing half to divide by
        # would score every such item at 0.4 for a right answer.
        reasoning = 0.0
        raw = answer_score
        components = {"answer": answer_score}
        detail = f"answer {'correct' if answer.correct else answer.detail}; no reasoning rubric"

    retention = hint_retention(hints_revealed)
    if hints_revealed:
        detail += f"; {hints_revealed} hint(s) taken, keeping {retention:.0%}"
    components["hint_retention"] = round(retention, 4)

    evidence = evidence_from(judgements, grader_version=GRADER_VERSION)
    if answer.stated:
        # An answer nobody gave is not an answer anybody got wrong. Same rule as a rubric
        # criterion the candidate never addressed: silence writes nothing.
        evidence = (
            Evidence(
                concept_id=item.primary_concept,
                score=answer_score,
                confidence=answer.confidence,
                grader_version=GRADER_VERSION,
            ),
            *evidence,
        )

    return QuantGrade(
        status="graded",
        item_id=item.id,
        score=round(raw * retention, 4),
        hints_revealed=hints_revealed,
        answer=answer,
        judgements=judgements,
        evidence=evidence,
        summary=summary,
        detail=detail,
        components=components,
    )
