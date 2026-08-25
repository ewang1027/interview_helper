"""Corpus routes. Moved from the root to `/api/v1` with the router (docs/API.md).

Everything here reads the **corpus**, not the database. The corpus is a build-time
artifact that cannot change inside a running process (docs/CORPUS.md), so it is loaded
once and cached; `items` in Postgres is a projection of it, and its only column that
drifts is the live `elo`, which nothing here reports.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, col, select

from api.auth import CurrentPrincipal
from api.db import get_session
from api.errors import not_found
from api.models import Artifact, InterviewSession
from corpus.loader import load_concepts, load_items

router = APIRouter(tags=["corpus"])

DbSession = Annotated[Session, Depends(get_session)]


@lru_cache
def _corpus_status() -> dict[str, Any]:
    """Cached: the corpus is a build-time artifact (docs/CORPUS.md) and does not change
    within a running process, so reloading it from disk per request was pure waste."""
    concepts = load_concepts()
    items = load_items()
    by_domain: dict[str, int] = {}
    for concept in concepts:
        by_domain[concept.domain] = by_domain.get(concept.domain, 0) + 1
    return {
        "concepts": len(concepts),
        "concepts_by_domain": by_domain,
        "items": len(items),
        "archetypes": sum(1 for i in items if i.kind == "archetype"),
        "instances": sum(1 for i in items if i.kind == "instance"),
    }


@lru_cache
def _concepts() -> list[dict[str, Any]]:
    """The taxonomy, with its prerequisite edges and what each concept unlocks.

    `unlocks` is derived here rather than stored: it is the reverse of `prereqs`, and a
    second hand-maintained copy of one relationship is a second thing to get wrong. It is
    what makes the DAG drawable from one request.
    """
    concepts = load_concepts()
    unlocks: dict[str, list[str]] = {concept.id: [] for concept in concepts}
    for concept in concepts:
        for prereq in concept.prereqs:
            if prereq in unlocks:
                unlocks[prereq].append(concept.id)

    # Which concepts any item measures as its *primary* — the planner serves only these,
    # and the difference between "ranked" and "servable" is a thing this project has
    # already been caught reporting imprecisely (docs/ADAPTIVE.md).
    primary = {item.primary_concept for item in load_items()}
    tagged: set[str] = set()
    for item in load_items():
        tagged.add(item.primary_concept)
        tagged.update(item.concepts)

    return [
        {
            "id": concept.id,
            "name": concept.name,
            "domain": concept.domain,
            "description": concept.description,
            "band": concept.band,
            "tags": list(concept.tags),
            "prereqs": list(concept.prereqs),
            "unlocks": sorted(unlocks[concept.id]),
            "servable": concept.id in primary,
            "measured_by_some_item": concept.id in tagged,
        }
        for concept in concepts
    ]


@lru_cache
def _items_index() -> list[dict[str, Any]]:
    """Every item, as metadata. **No statement, ever** — see `corpus_item` below."""
    return [
        {
            "id": item.id,
            "kind": item.kind,
            "domain": item.domain,
            "modality": item.modality,
            "title": item.title,
            "primary_concept": item.primary_concept,
            "concepts": list(item.concepts),
            "difficulty_band": item.difficulty.band,
            "elo": item.difficulty.elo,
            "expected_minutes": item.expected_minutes,
            "archetype_id": item.archetype_id,
        }
        for item in load_items()
    ]


@lru_cache
def _item_statements() -> dict[str, str]:
    return {item.id: item.statement_md for item in load_items()}


@router.get("/corpus/status")
def corpus_status() -> dict[str, Any]:
    """What content this build actually has. Useful before there is a UI."""
    return _corpus_status()


@router.get("/concepts")
def list_concepts(
    principal: CurrentPrincipal,
    domain: Annotated[str | None, Query()] = None,
) -> dict[str, Any]:
    """The whole taxonomy: names, domains, the prerequisite DAG, and what is servable.

    Added 2026-08-24 because the web app needed it and nothing provided it. `GET /mastery`
    returns only *measured* concepts and carries no name or domain — it projects the
    mastery table alone — so drawing the taxonomy meant assembling it from one weakness
    ranking per mode, four requests to answer a question about static build-time content.
    """
    rows = _concepts()
    if domain is not None:
        rows = [row for row in rows if row["domain"] == domain]
    return {
        "concepts": rows,
        "total": len(rows),
        # Stated because the gap between them is a policy, not a corpus gap: the ranking
        # covers everything, the planner serves only what some item measures as primary.
        "servable": sum(1 for row in rows if row["servable"]),
    }


@router.get("/corpus/items")
def list_items(
    db: DbSession,
    principal: CurrentPrincipal,
    domain: Annotated[str | None, Query()] = None,
    concept_id: Annotated[str | None, Query()] = None,
) -> dict[str, Any]:
    """Browse the corpus. **Metadata only — no statement is returned by this route at all**,
    seen or unseen, so listing can never be a way to read ahead."""
    seen = _seen_item_ids(db, principal.user_id)
    rows = [
        {**row, "seen": row["id"] in seen}
        for row in _items_index()
        if (domain is None or row["domain"] == domain)
        and (
            concept_id is None
            or concept_id == row["primary_concept"]
            or concept_id in row["concepts"]
        )
    ]
    return {"items": rows, "total": len(rows), "seen": sum(1 for row in rows if row["seen"])}


@router.get("/corpus/items/{item_id}")
def corpus_item(item_id: str, db: DbSession, principal: CurrentPrincipal) -> dict[str, Any]:
    """One item, with its statement **redacted unless you have been served it**.

    docs/API.md: reading ahead defeats the measurement. "Served" means the item appeared in
    the plan of one of your own sessions — not merely that it exists, and not that somebody
    else saw it. Hints and the grader's expected answers are never returned by this route
    regardless, because seeing an item once is not a reason to be handed its solution.
    """
    row = next((row for row in _items_index() if row["id"] == item_id), None)
    if row is None:
        raise not_found("item", item_id)

    seen = item_id in _seen_item_ids(db, principal.user_id)
    return {
        **row,
        "seen": seen,
        "statement_md": _item_statements()[item_id] if seen else None,
        "redacted": not seen,
    }


def _seen_item_ids(db: Session, user_id: str) -> set[str]:
    """Items this user has been served: planned in one of their sessions, or submitted to.

    Read from the plan rather than from artifacts alone — an item you were shown and did
    not answer has still been read, and redacting it afterwards would be theatre.
    """
    seen: set[str] = set()
    sessions = db.exec(
        select(InterviewSession).where(col(InterviewSession.user_id) == user_id)
    ).all()
    ids = [session.id for session in sessions]
    for session in sessions:
        for entry in (session.plan or {}).get("items", []):
            if entry.get("item_id"):
                seen.add(entry["item_id"])
    if ids:
        seen.update(
            artifact.item_id
            for artifact in db.exec(select(Artifact).where(col(Artifact.session_id).in_(ids))).all()
        )
    return seen
