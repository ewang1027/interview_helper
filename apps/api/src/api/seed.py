"""`make seed` / `python -m api.seed` — load the corpus into the database.

Idempotent: upserts by id, safe to re-run after a corpus refresh (docs/CORPUS.md's
"Refresh" section — items are append-only and retired via `deprecated_at`, never
deleted, which this mirrors).
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlmodel import Session, select

from api.db import get_engine
from api.models import Concept, ConceptEdge, Item, ItemConcept
from corpus.loader import load_concepts, load_items


def _as_datetime(d: date | None) -> datetime | None:
    if d is None:
        return None
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


def _upsert_concepts(session: Session) -> None:
    concepts = load_concepts()
    for c in concepts:
        concept_row = session.get(Concept, c.id)
        if concept_row is None:
            concept_row = Concept(id=c.id, domain=c.domain, name=c.name, description=c.description)
            session.add(concept_row)
        concept_row.domain = c.domain
        concept_row.name = c.name
        concept_row.description = c.description
        concept_row.band = c.band
        concept_row.tags = list(c.tags)
        concept_row.deprecated_at = _as_datetime(c.deprecated_at)
    session.flush()

    existing_edges = {(e.concept_id, e.prereq_id) for e in session.exec(select(ConceptEdge))}
    for c in concepts:
        for prereq_id in c.prereqs:
            if (c.id, prereq_id) not in existing_edges:
                session.add(ConceptEdge(concept_id=c.id, prereq_id=prereq_id))


def _upsert_items(session: Session) -> None:
    items = load_items()
    for i in items:
        item_row = session.get(Item, i.id)
        if item_row is None:
            item_row = Item(
                id=i.id,
                kind=i.kind,
                domain=i.domain,
                modality=i.modality,
                title=i.title,
                statement_md=i.statement_md,
                primary_concept_id=i.primary_concept,
                difficulty_band=i.difficulty.band,
                difficulty_elo=i.difficulty.elo,
                elo=i.difficulty.elo,
                corpus_version=i.corpus_version,
            )
            session.add(item_row)
        item_row.kind = i.kind
        item_row.domain = i.domain
        item_row.modality = i.modality
        item_row.title = i.title
        item_row.statement_md = i.statement_md
        item_row.primary_concept_id = i.primary_concept
        item_row.difficulty_band = i.difficulty.band
        item_row.difficulty_elo = i.difficulty.elo
        item_row.corpus_version = i.corpus_version
        item_row.archetype_id = i.archetype_id
        item_row.expected_minutes = i.expected_minutes
        item_row.grading = i.grading
        item_row.hints = list(i.hints)
        item_row.follow_ups = list(i.follow_ups)
        item_row.deprecated_at = _as_datetime(i.deprecated_at)
    session.flush()

    existing_links = {(link.item_id, link.concept_id) for link in session.exec(select(ItemConcept))}
    for i in items:
        for concept_id in i.concepts:
            if (i.id, concept_id) not in existing_links:
                session.add(ItemConcept(item_id=i.id, concept_id=concept_id))


def seed(session: Session) -> None:
    _upsert_concepts(session)
    _upsert_items(session)
    session.commit()


def main() -> None:
    with Session(get_engine()) as session:
        seed(session)
        concepts = session.exec(select(Concept)).all()
        items = session.exec(select(Item)).all()
        print(f"seeded {len(concepts)} concept(s), {len(items)} item(s)")


if __name__ == "__main__":
    main()
