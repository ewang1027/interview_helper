"""Practice-log routes — problems solved elsewhere, counted here.

docs/PRACTICE_LOG.md's REST surface. Two things depart from the session routes next door,
both deliberately:

- **`POST /practice/problems` is synchronous.** A submission is `202` because grading it
  may involve a sandbox and a complexity probe; this is one small structured-output call
  with nothing to wait on, and returning `201` with the classification already resolved is
  the difference between logging a problem and logging a problem and then polling for it.
- **The model client is a dependency**, exactly as it is for interviewer turns, so a test
  drives the whole route with a scripted classifier and no network.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from api import leetcode
from api import practice as service
from api.auth import CurrentPrincipal
from api.db import get_session
from api.errors import unavailable
from api.schemas import (
    ClassificationRequest,
    ImportLeetCodeRequest,
    LogProblemRequest,
    ReviewRequest,
)

router = APIRouter(tags=["practice"])


def get_classifier() -> Any:
    """The provider client for classification, or None to let `ModelRouter` build one."""
    return None


DbSession = Annotated[Session, Depends(get_session)]
Classifier = Annotated[Any, Depends(get_classifier)]


@router.post("/practice/problems", status_code=201)
def log_problem(
    body: LogProblemRequest,
    db: DbSession,
    principal: CurrentPrincipal,
    client: Classifier,
) -> dict[str, Any]:
    """Log a problem you solved elsewhere. Classifies it, and counts it if the tag is sure.

    Below the confidence gate the problem lands `pending_classification`: recorded and
    visible, out of the review queue, feeding nothing until you confirm or correct it.
    `concept_evidence` is immutable, so this is what stops a guess becoming a permanent
    fact about your mastery.
    """
    problem = service.log_problem(
        db,
        user_id=principal.user_id,
        title=body.title,
        url=body.url,
        source_site=body.source_site,
        notes=body.notes,
        difficulty_label=body.difficulty_label,
        solved_at=body.solved_at,
        client=client,
    )
    return service.problem_detail(db, problem.id)


@router.post("/practice/import/leetcode", status_code=201)
def import_leetcode(
    body: ImportLeetCodeRequest,
    db: DbSession,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    """Import LeetCode problems by slug or URL, or from a public profile's recent solves.

    Metadata only — a title, a difficulty and the topic tags. No problem statement is
    requested or stored, which is what keeps this inside docs/PRACTICE_LOG.md's rule
    rather than an exception to it.

    Everything imported lands `pending_classification` with the concept its tags name
    already selected. That is deliberate and not a limitation: a resolved classification
    cannot be re-tagged, because its evidence is written and evidence is immutable — so a
    wrong auto-accept would be permanent, while a suggestion costs one confirmation.
    """
    slugs = list(body.slugs)
    if body.username:
        try:
            slugs += [solve.slug for solve in leetcode.recent_solves(body.username)]
        except leetcode.LeetCodeError as exc:
            raise unavailable(f"LeetCode: {exc}") from exc
    return service.import_from_leetcode(db, user_id=principal.user_id, slugs=slugs)


@router.get("/practice/problems")
def list_problems(
    db: DbSession,
    principal: CurrentPrincipal,
    concept_id: Annotated[str | None, Query()] = None,
    status: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(gt=0, le=100)] = 50,
    cursor: Annotated[str | None, Query()] = None,
) -> dict[str, Any]:
    return service.list_problems(
        db, concept_id=concept_id, status=status, limit=limit, cursor=cursor
    )


# Before `/practice/problems/{problem_id}` would be a different path entirely, but the
# review queue is registered here anyway so the file reads in the order docs/API.md lists.
@router.get("/practice/review-queue")
def review_queue(db: DbSession, principal: CurrentPrincipal) -> dict[str, Any]:
    """What is due to be solved again, most overdue first."""
    return service.review_queue(db)


@router.get("/practice/problems/{problem_id}")
def get_problem(db: DbSession, principal: CurrentPrincipal, problem_id: str) -> dict[str, Any]:
    """The problem, every solve of it, and the evidence those solves produced."""
    return service.problem_detail(db, problem_id)


@router.patch("/practice/problems/{problem_id}/classification")
def set_classification(
    body: ClassificationRequest,
    db: DbSession,
    principal: CurrentPrincipal,
    problem_id: str,
) -> dict[str, Any]:
    """Confirm or correct a proposed classification. This is what writes the held evidence."""
    service.resolve_classification(
        db,
        problem_id,
        user_id=principal.user_id,
        primary_concept_id=body.primary_concept_id,
        secondary_concept_ids=body.secondary_concept_ids,
    )
    return service.problem_detail(db, problem_id)


@router.post("/practice/problems/{problem_id}/reviews", status_code=201)
def record_review(
    body: ReviewRequest,
    db: DbSession,
    principal: CurrentPrincipal,
    problem_id: str,
) -> dict[str, Any]:
    """Record a scheduled re-solve. Success advances the schedule; a miss shortens it."""
    service.record_review(
        db,
        problem_id,
        user_id=principal.user_id,
        is_success=body.is_success,
        notes=body.notes,
        attempted_at=body.attempted_at,
    )
    return service.problem_detail(db, problem_id)
