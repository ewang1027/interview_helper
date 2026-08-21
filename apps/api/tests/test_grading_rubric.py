"""The rubric grader, with a scripted model.

The interesting behaviour is not "does it average the weights". It is what it does with a
judgement it cannot trust: a citation that is not in the answer, a criterion the model
skipped, an answer that addressed half the rubric. Each of those has a different right
outcome, and conflating any two of them writes evidence that is not true.

**Marked `db`, which is not obvious for a test of a pure function.** The grader writes
nothing, but the call it makes does: `api.llm` records an `llm_calls` row for every model
call, scripted or not, because a grader that could avoid the ledger by being faked would be
a grader whose cost is invisible in exactly the runs that exercise it most. The first draft
of this file left eleven orphan rows in the development database before that was noticed.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fakes import ScriptedModel, model_response, text_block
from sqlmodel import Session, col, delete, select

from api.db import get_engine
from api.grading.rubric import (
    GRADER_VERSION,
    RUBRIC_CONFIDENCE,
    cites_the_answer,
    grade_rubric,
    response_schema,
)
from api.models import LlmCall
from api.settings import Settings
from corpus.loader import load_items

pytestmark = pytest.mark.db

ITEMS = {item.id: item for item in load_items()}
DESIGN = ITEMS["i.design.0001"]
CODING = ITEMS["i.code.0001"]
CRITERIA = DESIGN.grading["criteria"]

ANSWER = (
    "Start with the delivery volume: forty thousand notices a day times an average of "
    "sixty subscribers is about two and a half million deliveries, and the worst single "
    "notice reaches two million riders on its own. That worst case is what decides where "
    "fanout happens, so I would resolve the biggest routes at read time and precompute "
    "the tail."
)


@pytest.fixture(autouse=True)
def _ledger():
    """Remove exactly the rows these tests caused. They are real ledger rows for calls that
    were really made — against a fake, at no cost, but the ledger cannot tell and should
    not have to."""
    with Session(get_engine()) as db:
        before = set(db.exec(select(LlmCall.id)).all())
    yield
    with Session(get_engine()) as db:
        new = set(db.exec(select(LlmCall.id)).all()) - before
        if new:
            db.exec(delete(LlmCall).where(col(LlmCall.id).in_(new)))
            db.commit()


def settings() -> Settings:
    return Settings(session_secret="x", model_grader="us.anthropic.claude-sonnet-4-6")


def verdict(criterion_id: str, *, level: float, citation: str, demonstrated: bool = True) -> dict:
    return {
        "id": criterion_id,
        "demonstrated": demonstrated,
        "level": level,
        "citation": citation,
        "reasoning": "because of the quoted span",
    }


def scripted(*verdicts: dict[str, Any], summary: str = "A solid answer.") -> ScriptedModel:
    payload = json.dumps({"criteria": list(verdicts), "summary": summary})
    return ScriptedModel(model_response(text_block(payload)))


def grade(model: ScriptedModel, answer: str = ANSWER, **kwargs: Any):
    return grade_rubric(DESIGN, answer, client=model, settings=settings(), **kwargs)


# --- The request ------------------------------------------------------------------------


def test_the_rubric_and_its_anchors_are_sent_verbatim():
    """docs/GRADING.md: without anchors the grader scores on vibe and drifts between runs.
    Summarising them into the prompt would be the same failure, more slowly."""
    model = scripted(verdict(CRITERIA[0]["id"], level=4, citation="delivery volume"))
    grade(model)

    prompt = model.requests[0]["messages"][0]["content"]
    for criterion in CRITERIA:
        assert criterion["id"] in prompt
        assert criterion["description"] in prompt
        for text in (criterion.get("levels") or {}).values():
            assert text in prompt
    assert DESIGN.statement_md in prompt
    assert ANSWER in prompt


def test_the_response_is_constrained_to_this_items_criteria():
    """An `enum` of the item's own ids, so a judgement of something not on the rubric
    cannot be expressed rather than having to be filtered out afterwards."""
    schema = response_schema([c["id"] for c in CRITERIA])
    ids = schema["properties"]["criteria"]["items"]["properties"]["id"]
    assert ids["enum"] == [c["id"] for c in CRITERIA]
    assert schema["additionalProperties"] is False

    model = scripted(verdict(CRITERIA[0]["id"], level=2, citation="delivery volume"))
    grade(model)
    assert model.requests[0]["output_config"]["format"]["type"] == "json_schema"


def test_grading_is_routed_as_the_grading_job():
    model = scripted(verdict(CRITERIA[0]["id"], level=2, citation="delivery volume"))
    grade(model)
    assert model.requests[0]["model"] == "us.anthropic.claude-sonnet-4-6"
    assert model.requests[0]["output_config"]["effort"] == "high"


# --- Judging ------------------------------------------------------------------------------


def test_a_cited_judgement_scores_and_becomes_evidence():
    citation = "the worst single notice reaches two million riders"
    result = grade(scripted(verdict(CRITERIA[0]["id"], level=4, citation=citation)))

    judged = next(j for j in result.judgements if j.id == CRITERIA[0]["id"])
    assert judged.demonstrated and judged.citation_verified
    assert judged.score == 1.0
    assert result.score == pytest.approx(CRITERIA[0]["weight"])
    assert [(e.concept_id, e.score, e.confidence) for e in result.evidence] == [
        (CRITERIA[0]["concept"], 1.0, RUBRIC_CONFIDENCE)
    ]
    assert all(e.grader_version == GRADER_VERSION for e in result.evidence)


def test_a_citation_that_is_not_in_the_answer_costs_the_criterion():
    """The one control separating "the model read the answer" from "the model wrote a
    plausible review of an answer"."""
    result = grade(
        scripted(verdict(CRITERIA[0]["id"], level=4, citation="I calculated the p99 latency"))
    )
    judged = next(j for j in result.judgements if j.id == CRITERIA[0]["id"])
    assert not judged.citation_verified
    assert not judged.demonstrated
    assert judged.score == 0.0
    assert "citation not found" in judged.reasoning
    assert result.evidence == ()


def test_not_demonstrated_scores_zero_and_writes_no_evidence():
    """Two different things, and conflating them tells the adaptive engine you are weak at
    something it never observed."""
    result = grade(
        scripted(
            verdict(CRITERIA[0]["id"], level=0, citation="", demonstrated=False),
            verdict(CRITERIA[1]["id"], level=4, citation="resolve the biggest routes at read time"),
        )
    )
    assert result.score == pytest.approx(CRITERIA[1]["weight"])
    assert [e.concept_id for e in result.evidence] == [CRITERIA[1]["concept"]]
    assert CRITERIA[0]["id"] in result.as_detail()["not_demonstrated"]


def test_a_criterion_the_model_skipped_is_not_demonstrated():
    """Nothing said about it is the same conclusion as the candidate not addressing it, and
    it is the honest one — nothing says otherwise."""
    result = grade(scripted(verdict(CRITERIA[0]["id"], level=4, citation="delivery volume is")))
    skipped = [j for j in result.judgements if j.id != CRITERIA[0]["id"]]
    assert skipped and all(not j.demonstrated for j in skipped)
    assert all("returned no judgement" in j.reasoning for j in skipped)


def test_every_criterion_judged_gives_the_weighted_total():
    verdicts = [
        verdict(criterion["id"], level=4, citation="delivery volume is what decides")
        for criterion in CRITERIA
    ]
    # A citation that is genuinely in the answer, for every criterion.
    verdicts = [
        verdict(criterion["id"], level=4, citation="what decides where fanout happens")
        for criterion in CRITERIA
    ]
    result = grade(scripted(*verdicts))
    assert result.score == pytest.approx(1.0)
    assert len(result.evidence) == len(CRITERIA)


def test_hints_cost_a_rubric_score_the_same_way_they_cost_a_coding_one():
    verdicts = [
        verdict(criterion["id"], level=4, citation="what decides where fanout happens")
        for criterion in CRITERIA
    ]
    result = grade(scripted(*verdicts), hints_revealed=2)
    assert result.score == pytest.approx(0.95 * 0.90)
    assert result.components["rubric"] == pytest.approx(1.0)


# --- Refusals -------------------------------------------------------------------------------


def test_an_item_with_no_rubric_is_refused_rather_than_guessed_at():
    with pytest.raises(ValueError, match="not graded by rubric"):
        grade_rubric(CODING, ANSWER, client=scripted(), settings=settings())


def test_an_empty_answer_is_refused():
    with pytest.raises(ValueError, match="empty answer"):
        grade(scripted(), answer="   ")


def test_a_grader_that_does_not_answer_in_json_raises():
    """A grader that shrugged and scored zero would write evidence of weakness from its own
    bug, which is the one thing docs/GRADING.md says must never happen."""
    with pytest.raises(ValueError, match="did not answer with JSON"):
        grade(ScriptedModel(model_response(text_block("I think it was pretty good?"))))


def test_a_response_with_no_criteria_array_raises():
    payload = json.dumps({"summary": "nice"})
    with pytest.raises(ValueError, match="no criteria"):
        grade(ScriptedModel(model_response(text_block(payload))))


# --- The citation check itself ------------------------------------------------------------


@pytest.mark.parametrize(
    ("citation", "expected"),
    [
        ("the worst single notice reaches two million riders", True),
        ("The Worst Single Notice   reaches\ntwo million riders", True),
        ("I calculated the p99 latency and it was fine", False),
        ("the", False),
        ("", False),
        ("two million", False),
    ],
)
def test_the_citation_check_forgives_formatting_and_nothing_else(citation, expected):
    """Reflowing a quotation across line breaks is still quoting it; inventing a sentence is
    not. A quote shorter than a phrase is a substring of everything and evidence of
    nothing."""
    assert cites_the_answer(citation, ANSWER) is expected


def test_the_grader_module_itself_reaches_nothing():
    """Purity of the *grader* is what lets a grade be re-run over a stored artifact without
    writing duplicate history. The layer below it does write — one `llm_calls` row per call
    — and that is why this module is marked `db`."""
    import inspect

    from api.grading import rubric

    source = inspect.getsource(rubric)
    assert "get_engine" not in source
    assert "Session(" not in source
    assert "ExecutorClient" not in source
