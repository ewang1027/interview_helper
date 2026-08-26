"""The two schemas fixed on 2026-08-26, sent to a real provider so the fix is verified.

`test_output_schemas.py` proves these carry no keyword the API rejects. That is a static
check against a rule written down by hand, and a rule written down by hand can be wrong or
incomplete — so this sends each schema to the provider and lets it be the judge.

Marked `llm`: it spends money and needs credentials.

    make test-llm

**Why this file exists at all.** `api.practice.response_schema` and
`api.grading.rubric.response_schema` both carried range keywords that structured outputs
reject, from Phase 9 and Phase 3 respectively, and neither was ever caught — because every
test of both used a scripted client, which answers whatever it is handed and never
validates the request. The rubric one is the expensive case: the buildlog claimed all four
interview modes grade, and design and behavioral could not have, because their grader would
have returned a 400 on the first real call.

Two small calls, deliberately: the assertion is that the **request shape is accepted**, not
that the answer is good. What the graders and the classifier actually decide is tested at
length elsewhere, against scripted answers, where it costs nothing.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlmodel import Session, col, delete, select

from api import practice
from api.db import get_engine
from api.errors import ProblemError
from api.grading import rubric
from api.models import LlmCall
from api.settings import get_settings
from corpus.loader import load_items

pytestmark = pytest.mark.llm


@pytest.fixture(autouse=True)
def ledger() -> Iterator[None]:
    """Remove the ledger rows these calls write. They are real calls and really cost money;
    the rows go because the development database is not where this repo keeps its bills."""
    with Session(get_engine()) as db:
        before = set(db.exec(select(LlmCall.id)).all())
    yield
    with Session(get_engine()) as db:
        new = set(db.exec(select(LlmCall.id)).all()) - before
        if new:
            db.exec(delete(LlmCall).where(col(LlmCall.id).in_(new)))
            db.commit()


def test_the_practice_classifier_schema_is_accepted_by_a_real_provider() -> None:
    """Phase 9's classifier, which would have 400'd on every real call until today.

    `classify` swallows every failure by design — a provider that is down must not lose
    somebody's log entry — so a broken schema would surface here as a *successful* call
    with an empty classification and a `reasoning` string naming the error. That is exactly
    how this defect stayed invisible, and it is why the assertion below is on `reasoning`
    rather than on an exception.
    """
    settings = get_settings()
    result = practice.classify(
        title="Longest Substring Without Repeating Characters",
        url="https://leetcode.com/problems/longest-substring-without-repeating-characters/",
        settings=settings,
    )

    assert "not supported" not in result.reasoning, f"the schema was rejected: {result.reasoning}"
    assert "unavailable" not in result.reasoning, f"provider unavailable: {result.reasoning}"
    assert result.primary_concept_id in practice.concept_ids()
    assert 0.0 <= result.confidence <= 1.0
    # Four is the cap `maxItems` used to express and `classify` now enforces.
    assert len(result.secondary_concept_ids) <= practice.MAX_SECONDARIES

    print(
        f"\nclassify: {result.primary_concept_id} "
        f"(+{len(result.secondary_concept_ids)}) conf={result.confidence:.2f} · {result.model}"
        f"\n  {result.reasoning}"
    )


def test_the_rubric_grader_schema_is_accepted_by_a_real_provider() -> None:
    """Phase 3's rubric grader — the half of the grading surface that has never run live.

    Design and behavioral both go through this. A 400 here is the difference between "all
    four modes grade" and "two of them do", which is what the buildlog said until this ran.
    """
    settings = get_settings()
    items = {item.id: item for item in load_items()}
    design = items["i.design.0001"]
    answer = (
        "Start from the delivery volume: forty thousand notices a day against an average "
        "of sixty subscribers is roughly two and a half million deliveries, and the worst "
        "single notice reaches two million riders by itself. That worst case decides where "
        "fanout happens — I would resolve the largest routes at read time and precompute "
        "the long tail, so the write path stays bounded and the read path only pays for "
        "the routes that are actually hot."
    )

    try:
        graded = rubric.grade_rubric(design, answer, settings=settings)
    except ProblemError as exc:
        pytest.fail(f"the rubric grader was refused: {exc.detail}")

    assert graded.judgements, "no criteria were judged"
    for judgement in graded.judgements:
        # The bound that used to live in the schema, now clamped in `_judge`. A real model
        # is unlikely to exceed it — the point is that nothing can.
        assert 0.0 <= judgement.level <= judgement.level_max
        assert 0.0 <= judgement.score <= 1.0
    assert 0.0 <= graded.score <= 1.0

    print(
        f"\nrubric: score {graded.score:.2f} over {len(graded.judgements)} criteria\n"
        + "\n".join(
            f"  {j.id:34} {j.level}/{j.level_max} "
            f"{'demonstrated' if j.demonstrated else 'not shown':14}"
            for j in graded.judgements
        )
    )
