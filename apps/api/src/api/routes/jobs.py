"""Job-application routes — docs/JOBS.md's REST surface.

Two things depart from the practice-log routes next door, and both follow from the same
fact: an application is not evidence.

- **`POST /jobs/import` is synchronous and returns `201` with the rows already written.**
  It can make two model calls and the second one reaches the network, so it is the slowest
  route in this file — but an import that returned `202` would mean polling to find out
  what it added, and the thing a person wants to see after pasting a list is the list.
- **A low-confidence tag blocks nothing.** In the practice log the confidence gate holds
  back an immutable evidence write. Here it only marks a row for review, because a
  mis-tagged application mis-colours a chart and nothing else.

Both model clients are dependencies, exactly as the interviewer's and the classifier's
are, so a test drives the whole import — parse *and* research — with scripted responses
and never opens a socket.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from api import jobs as service
from api.auth import CurrentPrincipal
from api.db import get_session
from api.schemas import (
    CreateJobRequest,
    ImportJobsRequest,
    JobClassificationRequest,
    StageRequest,
)
from api.settings import Settings, get_settings

router = APIRouter(tags=["jobs"])


def get_job_parser() -> Any:
    """The provider client for the parse, or None to let `ModelRouter` build one."""
    return None


def get_job_researcher() -> Any:
    """The provider client for the research pass.

    Separate from the parser's even though both resolve to None in production: the two
    calls run at different tiers against different tools, and a test that scripts one has
    to be able to leave the other alone.
    """
    return None


DbSession = Annotated[Session, Depends(get_session)]
Config = Annotated[Settings, Depends(get_settings)]
Parser = Annotated[Any, Depends(get_job_parser)]
Researcher = Annotated[Any, Depends(get_job_researcher)]


@router.get("/jobs/catalog")
def catalog() -> dict[str, Any]:
    """The stage ladder and the category taxonomy.

    Served rather than duplicated in the web app: the enum the model is constrained to and
    the buttons a person clicks have to be the same list, and the only way to guarantee
    that is for there to be one list.
    """
    return service.catalog_view()


@router.post("/jobs/import", status_code=201)
def import_jobs(
    body: ImportJobsRequest,
    db: DbSession,
    principal: CurrentPrincipal,
    settings: Config,
    parser: Parser,
    researcher: Researcher,
) -> dict[str, Any]:
    """Paste a list of applications. Parses and tags them; researches long lists.

    The response reports `researched` and `research_skipped` rather than hiding the
    difference, because "the model looked these up" and "the model read what you typed"
    produce rows that look identical and are not equally trustworthy.
    """
    outcome = service.ingest(
        db,
        user_id=principal.user_id,
        text=body.text,
        client=parser,
        research_client=researcher,
        settings=settings,
    )
    return {
        "created": len(outcome.created),
        "duplicates": len(outcome.duplicates),
        "researched": outcome.researched,
        "research_skipped": outcome.research_skipped,
        "model": outcome.model,
        "cost_usd": round(outcome.cost_usd, 6),
        "web_searches": outcome.web_searches,
        "applications": service.list_applications(db, user_id=principal.user_id)["applications"],
    }


@router.post("/jobs", status_code=201)
def create_job(
    body: CreateJobRequest,
    db: DbSession,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    """Add one application by hand. No model call."""
    application = service.create_application(
        db,
        user_id=principal.user_id,
        company=body.company,
        role=body.role,
        location=body.location,
        url=body.url,
        subcategory=body.subcategory,
        stage=body.stage,
        notes=body.notes,
        applied_at=body.applied_at,
        source="manual",
    )
    db.commit()
    return service.application_detail(db, application.id)


@router.get("/jobs")
def list_jobs(
    db: DbSession,
    principal: CurrentPrincipal,
    category: Annotated[str | None, Query()] = None,
    stage: Annotated[str | None, Query()] = None,
    outcome: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(gt=0, le=500)] = 200,
) -> dict[str, Any]:
    return service.list_applications(
        db,
        user_id=principal.user_id,
        category=category,
        stage=stage,
        outcome=outcome,
        limit=limit,
    )


# Registered before `/jobs/{application_id}` so the literal path wins the match. FastAPI
# resolves in declaration order, and `stats` would otherwise arrive as an application id.
@router.get("/jobs/stats")
def stats(db: DbSession, principal: CurrentPrincipal) -> dict[str, Any]:
    """The funnel, the conversion rates and the category breakdown — everything the
    charts draw, from one pass over the applications."""
    return service.stats(db, user_id=principal.user_id)


@router.post("/jobs/recompute")
def recompute(db: DbSession, principal: CurrentPrincipal) -> dict[str, Any]:
    """Rebuild every application's stage projection from its events.

    The analogue of `POST /mastery/recompute`, and it exists for the same reason: the
    board is derived from the history, and a projection you cannot rebuild is a projection
    you cannot check.
    """
    return {"recomputed": service.recompute_all(db, user_id=principal.user_id)}


@router.get("/jobs/{application_id}")
def get_job(db: DbSession, principal: CurrentPrincipal, application_id: str) -> dict[str, Any]:
    """The application and every stage it has been in."""
    return service.application_detail(db, application_id)


@router.post("/jobs/{application_id}/stage", status_code=201)
def set_stage(
    body: StageRequest,
    db: DbSession,
    principal: CurrentPrincipal,
    application_id: str,
) -> dict[str, Any]:
    """Move to a stage. Appends to the history rather than overwriting the current one."""
    service.advance(
        db,
        application_id,
        stage=body.stage,
        note=body.note,
        occurred_at=body.occurred_at,
    )
    return service.application_detail(db, application_id)


@router.patch("/jobs/{application_id}/classification")
def set_classification(
    body: JobClassificationRequest,
    db: DbSession,
    principal: CurrentPrincipal,
    application_id: str,
) -> dict[str, Any]:
    """Confirm or correct the tag a parse proposed."""
    service.set_classification(db, application_id, subcategory=body.subcategory)
    return service.application_detail(db, application_id)


@router.delete("/jobs/{application_id}", status_code=204)
def delete_job(db: DbSession, principal: CurrentPrincipal, application_id: str) -> None:
    """Remove an application and its history — for a row a parse invented, mostly."""
    service.delete_application(db, application_id)
