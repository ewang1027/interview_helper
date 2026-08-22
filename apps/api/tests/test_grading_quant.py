"""The quant grader: a deterministic answer check, and a derivation judged beside it.

Split on purpose. The answer check is pure — no model, no database — so it runs in `make
check`, which is where a wall around a parser belongs: the interesting inputs are the
hostile ones and they should be exercised on every commit. The tests of the grade itself
make a model call, and `api.llm` writes an `llm_calls` row for every call including a
scripted one, so those are marked `db` and clean up exactly the rows they caused.

What is worth testing here is not the arithmetic. It is what the grader does with a
derivation that mentions numbers which are not the answer, which is every real one: a
sanity bound, a decoy the problem exists to refute, an intermediate value. Reading the
wrong number out of a correct answer writes evidence of a weakness the candidate does not
have, and mastery is derived from those rows, so it does not wash out.
"""

from __future__ import annotations

import json
import time
from typing import Any

import pytest
import sympy
from fakes import ScriptedModel, model_response, text_block
from sqlmodel import Session, col, delete, select

from api.db import get_engine
from api.grading.quant import (
    ANSWER_WEIGHT,
    DECLARED_CONFIDENCE,
    GRADER_VERSION,
    INFERRED_CONFIDENCE,
    accepted_form,
    check_answer,
    closing_statement,
    equivalent,
    expressions,
    grade_quant,
    rounds_to,
    safe_parse,
)
from api.models import LlmCall
from api.settings import Settings
from corpus.loader import load_items

ITEMS = {item.id: item for item in load_items()}
TOKENS = ITEMS["i.quant.0001"]  # exact "39"
DICE = ITEMS["i.quant.0002"]  # exact "149/20", numeric 7.45
PARCELS = ITEMS["i.quant.0003"]  # exact "16/3", numeric 5.333...
DESIGN = ITEMS["i.design.0001"]
CRITERIA = TOKENS.grading["reasoning_rubric"]

SUBMISSION = (
    "Track the length of the current gold run, because the presses are independent and "
    "nothing before the current streak can matter.\n"
    "Let E0, E1, E2 be the expected further presses from a run of 0, 1 and 2 golds.\n"
    "Each press costs one, and a silver clears the run back to zero rather than dropping "
    "it by one, so E0 = 1 + (1/3)E1 + (2/3)E0 and similarly down the chain.\n"
    "Answer: 39 presses, which must exceed 27 because every silver wastes the run so far."
)
WRONG = SUBMISSION.replace("Answer: 39 presses", "Answer: 30 presses")
SILENT = (
    "Track the length of the current gold run, because the presses are independent and "
    "nothing before the current streak can matter.\n"
    "I would write one equation per state and solve the system, but I ran out of time "
    "before doing any of the algebra."
)


# --- The wall around the parser -----------------------------------------------------------


@pytest.mark.parametrize(
    "hostile",
    [
        "9**9**9",  # seven characters, passes every other check, never finishes
        "9^9^9",
        "2**70",  # a bounded tower is still an unbounded integer
        "__import__('os').system('id')",
        "eval('1')",
        "().__class__.__bases__",
        "factorial(99999)",
        "x" * 200,  # over the length cap
    ],
)
def test_the_parser_refuses_hostile_input_before_it_does_any_work(hostile):
    """docs/SECURITY.md: the wall comes before the work. `parse_expr` evaluates what it
    parses and what it parses here was typed by the candidate, so every bound is checked
    against the *text* — refusing after the parse would be refusing after the damage."""
    started = time.perf_counter()
    assert safe_parse(hostile) is None
    assert (time.perf_counter() - started) < 1.0


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ("1/3", "1/3"),
        ("2/6", "1/3"),
        ("3 + 9 + 27", "39"),
        ("16/3", "16/3"),
        ("1/(1/3)^3", "27"),  # `^` is exponentiation to a candidate and XOR to Python
        ("2^10", "1024"),
        ("sqrt(2)", "sqrt(2)"),
        ("1,024", "1024"),  # a thousands separator is not a tuple
    ],
)
def test_the_forms_a_quant_answer_actually_takes_all_parse(written, expected):
    """The first draft of the allowlist refused every one of these, including `1/3`, because
    `parse_expr` resolves its own rewritten source — `39` becomes `Integer(39)` — against the
    globals it is handed. Nothing failed: every case still matched through `accept_forms`."""
    parsed = safe_parse(written)
    assert parsed is not None
    assert parsed == sympy.sympify(expected)


def test_equivalence_is_symbolic_not_textual():
    """What makes 1/3, 2/6 and 0.333... one answer rather than three."""
    third = sympy.Rational(1, 3)
    assert equivalent(safe_parse("2/6"), third)
    assert equivalent(safe_parse("3 + 9 + 27"), sympy.Integer(39))
    assert not equivalent(safe_parse("1/4"), third)


# --- Reading the answer out of a derivation ------------------------------------------------


def test_a_declared_answer_wins_over_a_decoy_anywhere_above_it():
    """The problem's whole point is that 27 is wrong, so the derivation says 27 out loud."""
    statement, declared = closing_statement("The naive value is 1/(1/3)^3 = 27.\nAnswer: 39")
    assert declared and statement == "39"
    assert check_answer(TOKENS, "The naive value is 1/(1/3)^3 = 27.\nAnswer: 39").correct


def test_a_sanity_bound_after_the_answer_does_not_cost_the_answer():
    """ "39 presses, which must exceed 27" ends on the wrong number and is a correct answer.
    Reading only the last expression would fail a candidate for checking their work."""
    checked = check_answer(TOKENS, "So E0 = 39 presses, which must exceed 27.")
    assert checked.correct and checked.submitted == "39"


def test_the_conclusion_is_read_when_nothing_was_declared():
    checked = check_answer(TOKENS, "Setting up the three equations and solving gives 39.")
    assert checked.correct and checked.stated and not checked.declared


def test_an_answer_nobody_gave_is_not_an_answer_anybody_got_wrong():
    """Zero on the answer, but `stated` is false — and that is what stops evidence being
    written. Recording silence as failure would tell the engine you are weak at something
    it never observed."""
    checked = check_answer(TOKENS, "I set up the states but ran out of time.")
    assert not checked.stated and not checked.correct and checked.method == "none"


def test_an_undeclared_sanity_bound_is_read_as_the_answer_when_nothing_else_is():
    """The limitation, pinned rather than hidden. "which must exceed 27" is a check, not a
    claim — but with no declaration and no other arithmetic below it, the grader has
    nothing that distinguishes the two, and it reads the last conclusion it can see. This
    is the case `Answer:` exists for, and the reason a read answer is softer evidence than
    a declared one."""
    checked = check_answer(TOKENS, "The system solves.\nIt must exceed 27 in any case.")
    assert checked.stated and not checked.correct and checked.submitted == "27"


def test_the_classic_wrong_answer_is_read_as_wrong():
    checked = check_answer(TOKENS, "The presses are independent, so the answer is 27.")
    assert checked.stated and not checked.correct and checked.submitted == "27"


def test_an_intermediate_value_is_not_mistaken_for_the_answer():
    """6.75 is what a discard on roll one buys, and a real derivation says so."""
    assert not check_answer(DICE, "The remaining game is worth 6.75.").correct
    assert check_answer(DICE, "The remaining game is worth 6.75, so the value is 149/20.").correct


def test_an_undeclared_number_far_above_the_conclusion_was_not_stated():
    """A closing statement is a conclusion, not the best sentence on the page. Without a
    declaration there is nothing to distinguish a number buried in the working from the
    answer, and guessing is how the wrong one gets recorded."""
    filler = "\n".join(["then I checked the setup again"] * 20)
    assert not check_answer(TOKENS, f"It works out to 39.\n{filler}").stated


def test_a_declaration_wins_from_anywhere_and_the_last_one_wins():
    """Unambiguous in a way no heuristic improves on, so it is not subject to the window a
    guess is. A candidate who declares twice meant the second one."""
    filler = "\n".join(["then I checked the setup again"] * 20)
    assert check_answer(TOKENS, f"The answer works out to 39.\n{filler}").correct
    assert not check_answer(TOKENS, "Answer: 39\nOn reflection, answer: 27").correct


# --- Rounding and accepted forms -----------------------------------------------------------


def test_a_decimal_is_accepted_at_the_precision_it_was_written_to():
    """How a person reads 5.33 against 16/3. Refusing it writes evidence of a weakness the
    candidate does not have, which is the failure this grader is most able to cause."""
    assert rounds_to("5.33", 16 / 3)
    assert rounds_to("5.3333", 16 / 3)
    assert check_answer(PARCELS, "So the expected number is about 5.33.").method == "rounded"


def test_a_rounding_too_coarse_to_mean_anything_is_refused():
    """Otherwise "5" is a correct rounding of 16/3, and of nearly everything else."""
    assert not rounds_to("5", 16 / 3)
    assert not rounds_to("5.3", 16 / 3)
    assert not check_answer(PARCELS, "So the expected number is about 5.3.").correct


def test_an_accepted_form_covers_what_sympy_cannot_normalise():
    """A mixed number is not an expression; `accept_forms` is why it is still an answer."""
    checked = check_answer(PARCELS, "The answer is 5 1/3 changeovers.")
    assert checked.correct and checked.method == "accept_form"


def test_an_accepted_form_is_bounded_by_digits_but_not_by_punctuation():
    """A form must not match inside a longer number — and must still match at the end of a
    sentence, which is where an answer usually sits."""
    assert accepted_form("the answer is 5 1/3.", ["5 1/3"]) == "5 1/3"
    assert accepted_form("it came to 5 1/30 changeovers", ["5 1/3"]) is None
    assert accepted_form("i make it 15 1/3", ["5 1/3"]) is None


def test_a_form_the_parser_can_already_read_is_not_matched_as_text():
    """Found by authoring `i.quant.0006`, whose answer is 1: listing `1` as an accepted form
    matched the numerator of "about 1/9 of them, so 0.111" and marked a wrong answer
    correct. Anything parseable is already decided by the equivalence check; what belongs in
    this list is exactly what that check cannot read."""
    assert accepted_form("about 1/9 of them, so 0.111", ["1"]) is None
    assert accepted_form("i make it 5 1/3 changeovers", ["5 1/3", "1"]) == "5 1/3"


def test_the_strongest_method_that_fits_is_the_one_reported():
    """An equivalence sympy proved is a better thing to be right about than a substring of
    a sentence, so `accept_forms` is tried last. Trying it first hid a parser that refused
    every expression it was given."""
    assert check_answer(TOKENS, "Summing gives 3 + 9 + 27 presses.").method == "exact"
    assert check_answer(TOKENS, "The total is 39.").method == "exact"


# --- The grade ------------------------------------------------------------------------------


def settings() -> Settings:
    return Settings(session_secret="x", model_grader="us.anthropic.claude-sonnet-4-6")


CITATIONS = {
    "state_identification": "the length of the current gold run",
    "conditioning_setup": "a silver clears the run back to zero",
    "solve_and_sanity_check": "which must exceed 27 because every silver",
}


def scripted(*, level: float = 3, only: list[str] | None = None) -> ScriptedModel:
    """A judgement per criterion at `level`, each citing a span that is really there."""
    criteria = [
        {
            "id": criterion["id"],
            "demonstrated": True,
            "level": level,
            "citation": CITATIONS[criterion["id"]],
            "reasoning": "because of the quoted span",
        }
        for criterion in CRITERIA
        if only is None or criterion["id"] in only
    ]
    payload = json.dumps({"criteria": criteria, "summary": "A clean derivation."})
    return ScriptedModel(model_response(text_block(payload)))


@pytest.fixture
def ledger():
    """Remove exactly the `llm_calls` rows these tests caused — real rows for calls really
    made, against a fake, at no cost, which the ledger cannot tell and should not have to."""
    with Session(get_engine()) as db:
        before = set(db.exec(select(LlmCall.id)).all())
    yield
    with Session(get_engine()) as db:
        new = set(db.exec(select(LlmCall.id)).all()) - before
        if new:
            db.exec(delete(LlmCall).where(col(LlmCall.id).in_(new)))
            db.commit()


def grade(submission: str = SUBMISSION, model: Any = None, **kwargs: Any):
    return grade_quant(
        TOKENS, submission, client=model or scripted(), settings=settings(), **kwargs
    )


@pytest.mark.db
def test_a_right_number_from_a_right_derivation_scores_one(ledger):
    result = grade()
    assert result.status == "graded"
    assert result.score == pytest.approx(1.0)
    assert result.components == {"answer": 1.0, "reasoning": 1.0, "hint_retention": 1.0}


@pytest.mark.db
def test_a_right_number_alone_is_not_a_pass(ledger):
    """docs/GRADING.md, and the reason quant is not just an equality check: a memorised
    value and a derived one are indistinguishable from the value alone."""
    result = grade(model=scripted(only=[]))
    assert result.score == pytest.approx(ANSWER_WEIGHT)
    assert result.answer.correct


@pytest.mark.db
def test_a_sound_derivation_with_a_slipped_digit_keeps_what_the_reasoning_earned(ledger):
    """How an interviewer scores it. The rubric's own arithmetic criterion already docks
    the wrong value, so the miss is counted where it belongs rather than twice over."""
    result = grade_quant(TOKENS, WRONG, client=scripted(), settings=settings())
    assert not result.answer.correct
    assert result.score == pytest.approx(1.0 - ANSWER_WEIGHT)


@pytest.mark.db
def test_the_answer_and_the_criteria_both_write_evidence(ledger):
    """Separate evidence, per docs/GRADING.md: the answer writes against the primary
    concept at a deterministic confidence, each criterion against whichever concept it
    names at a rubric one. The primary concept is measured twice, by two different
    instruments, and both readings are real."""
    result = grade()
    rows = [(row.concept_id, row.score, row.confidence) for row in result.evidence]
    assert rows[0] == (TOKENS.primary_concept, 1.0, DECLARED_CONFIDENCE)
    assert sorted(rows[1:]) == sorted((criterion["concept"], 1.0, 0.5) for criterion in CRITERIA)
    assert all(row.grader_version == GRADER_VERSION for row in result.evidence)


@pytest.mark.db
def test_an_answer_read_out_of_a_sentence_is_a_softer_claim_than_a_declared_one(ledger):
    """The check is deterministic either way; what was inferred is *which expression* it
    was pointed at, and a mis-read is a wrong verdict about a right answer."""
    declared = grade()
    inferred = grade_quant(
        TOKENS,
        SUBMISSION.replace("Answer: 39 presses", "That solves to 39 presses"),
        client=scripted(),
        settings=settings(),
    )
    assert declared.answer.declared and declared.evidence[0].confidence == DECLARED_CONFIDENCE
    assert not inferred.answer.declared
    assert inferred.evidence[0].confidence == INFERRED_CONFIDENCE
    assert inferred.score == declared.score  # the score is unchanged; only the claim softens


@pytest.mark.db
def test_no_answer_stated_writes_no_answer_evidence(ledger):
    """Silence is not evidence, on the same reasoning that keeps a not-demonstrated
    criterion out of the evidence table."""
    model = scripted(only=["state_identification"])
    result = grade_quant(TOKENS, SILENT, client=model, settings=settings())

    assert not result.answer.stated
    assert [(row.concept_id, row.confidence) for row in result.evidence] == [
        ("markov-chain-absorption", 0.5)
    ]
    # Only what the one demonstrated criterion earned, discounted by the answer's weight.
    assert result.score == pytest.approx((1.0 - ANSWER_WEIGHT) * 0.4)


@pytest.mark.db
def test_hints_cost_a_quant_score_the_way_they_cost_every_other_one(ledger):
    assert grade(hints_revealed=2).score == pytest.approx(0.95 * 0.90)


@pytest.mark.db
def test_an_item_that_asks_only_for_a_number_is_graded_only_on_the_number(ledger):
    """`reasoning_rubric` is optional in the schema. Dividing by a half that does not exist
    would cap every such item at 0.4 for a right answer."""
    grading = {**TOKENS.grading}
    grading.pop("reasoning_rubric")
    item = TOKENS.model_copy(update={"grading": grading})
    result = grade_quant(item, SUBMISSION, client=scripted(), settings=settings())
    assert result.score == pytest.approx(1.0)
    assert result.judgements == ()
    assert len(result.evidence) == 1


def test_an_item_this_grader_does_not_own_is_refused_rather_than_scored():
    """Which grader runs is the item's decision. A grader that scored a rubric item by
    looking for a number in it would report a confident zero."""
    with pytest.raises(ValueError, match="not graded by answer"):
        grade_quant(DESIGN, SUBMISSION)
    with pytest.raises(ValueError, match="empty answer"):
        grade_quant(TOKENS, "   ")


def test_an_item_with_nothing_to_check_against_fails_rather_than_marking_everything_wrong():
    """The validator errors on this shape so it should never reach the grader. If it does,
    every submission is "wrong" against nothing — and a fabricated zero corrupts mastery
    permanently while a failed grading is merely visible."""
    hollow = TOKENS.model_copy(
        update={"grading": {"type": "answer", "answer": {"unit": "presses"}}}
    )
    with pytest.raises(ValueError, match="no `exact` or `numeric`"):
        grade_quant(hollow, SUBMISSION)


def test_a_comma_straight_after_the_answer_does_not_destroy_it():
    """`_TERM` swallowed the comma, producing the span `39,` — which `ALLOWED_CHARS` then
    refuses, because a comma is not an allowed character. A correct answer scored 0.0 at
    the highest confidence in the system, writing evidence of a weakness the candidate had
    just disproved. Only half the quant corpus was exposed: a decimal escapes, because
    `_THOUSANDS` strips a comma followed by exactly three digits."""
    checked = check_answer(TOKENS, "Answer: 39, which must exceed 27.")

    assert checked.correct and checked.submitted == "39"


def test_a_thousands_separator_is_still_part_of_the_number():
    assert expressions("1,234,567 in total") == ["1,234,567"]


def test_a_retrospective_mention_of_the_answer_does_not_outrank_the_conclusion():
    """A marker *above* the end of the working is not a declaration — it is the sentence
    every item whose trap is 27 has to write. The derivation below reaches 39 on its last
    line and used to be scored 0.0 at 0.9 confidence, because `answer is` on line two
    outranked `So E0 = 39 presses` on line four."""
    checked = check_answer(
        TOKENS,
        "Let E0 be the expected presses from an empty run.\n"
        "The naive answer is 27, since (1/3)^3 = 1/27.\n"
        "But a silver clears the run, so I condition: E0 = 3 + 9 + 27.\n"
        "So E0 = 39 presses.",
    )

    assert checked.correct and checked.submitted == "39"


def test_a_declaration_is_graded_on_what_was_declared_and_nothing_else():
    """`expressions` splits on non-operator words, so a declared *wrong* number used to be
    rescued by the right one appearing later in the candidate's own sentence — scoring 1.0
    at 0.9 confidence. A declaration is a commitment; it is graded as one."""
    checked = check_answer(TOKENS, "Final answer: 27, though 39 is what the recursion gives.")

    assert not checked.correct
    assert checked.declared and checked.submitted == "27"


def test_a_declaration_cannot_be_twelve_guesses():
    checked = check_answer(TOKENS, "Answer: 30 or 31 or 32 or 33 or 34 or 35 or 36 or 39")

    assert not checked.correct and checked.submitted == "30"


def test_an_exponent_tower_hidden_behind_parentheses_is_refused_not_evaluated():
    """`_EXPONENT`'s `[^\\s()]+` stops at a paren, so `(2)**(63)**(63)` presented two
    exponents of 63 — both under the limit — while meaning `2**(63**63)`. `MAX_NODES` is
    checked after the parse, so it never ran. Measured: fifteen characters, and
    `parse_expr` had not returned after ninety seconds, inside the API worker."""
    started = time.monotonic()

    assert safe_parse("(2)**(63)**(63)") is None

    assert time.monotonic() - started < 1.0
    assert safe_parse("2**10") == 1024  # a single exponent is still an answer form
