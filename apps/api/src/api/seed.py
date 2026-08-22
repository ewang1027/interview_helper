"""`make seed` / `python -m api.seed` — load the corpus into the database.

Idempotent: upserts by id, safe to re-run after a corpus refresh (docs/CORPUS.md's
"Refresh" section — items are append-only and retired via `deprecated_at`, never
deleted, which this mirrors).
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlmodel import Session, select

from api.db import get_engine
from api.mastery import recompute
from api.models import Concept, ConceptEdge, Item, ItemConcept
from api.users import single_user
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


def _upsert_items(session: Session) -> list[str]:
    """Returns the ids whose corpus prior changed, which the caller has to act on."""
    items = load_items()
    rebased: list[str] = []
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
        # `elo` is deliberately absent from this update block: it is the *live* rating,
        # drifted by real outcomes (docs/ADAPTIVE.md), and re-seeding after a corpus
        # refresh must not reset it to the author's prior. `difficulty_elo` is the prior
        # and is refreshed.
        item_row.kind = i.kind
        item_row.domain = i.domain
        item_row.modality = i.modality
        item_row.title = i.title
        item_row.statement_md = i.statement_md
        item_row.primary_concept_id = i.primary_concept
        item_row.difficulty_band = i.difficulty.band
        if item_row.difficulty_elo != i.difficulty.elo:
            rebased.append(item_row.id)
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
    return rebased


def seed(session: Session) -> list[str]:
    """Load the corpus into the database. Returns the items whose corpus prior changed.

    That return value is load-bearing, and the reason is the central claim of
    docs/ADAPTIVE.md: **mastery is derived, never stored as ground truth**, and
    `POST /mastery/recompute` must reproduce the live table exactly.

    `items.elo` drifts from real outcomes and a re-seed deliberately leaves it alone —
    but a re-seed *does* refresh `difficulty_elo`, and `recompute` rebuilds `elo` as
    `difficulty_elo` plus a replay of every evidence row. So the moment an author re-rates
    an existing item, the live table stands on the old prior and any replay stands on the
    new one, and they disagree for good. Measured: one full-marks attempt, then a prior
    moved 1600 -> 1680, and the replay came back 1677.56 against a live 1597.94, with the
    concept's ability 4.64 Elo apart. `recompute` is the documented repair tool for a
    grader bug; here it was the thing doing the damage.

    Nothing could see it, either: the test suite replays after every test, so a dev
    database is permanently rebased and only a long-lived one diverges.
    """
    _upsert_concepts(session)
    rebased = _upsert_items(session)
    session.commit()
    return rebased


def main() -> None:
    with Session(get_engine()) as session:
        rebased = seed(session)
        concepts = session.exec(select(Concept)).all()
        items = session.exec(select(Item)).all()
        print(f"seeded {len(concepts)} concept(s), {len(items)} item(s)")
        if rebased:
            # Rebuilt here rather than left for someone to notice: the two paths have to
            # stand on the same prior, and the only moment that is knowable is the one
            # where the prior changed.
            user = single_user(session)
            recompute(session, user.id)
            session.commit()
            print(
                f"re-rated {len(rebased)} item(s) ({', '.join(sorted(rebased)[:5])}"
                f"{'...' if len(rebased) > 5 else ''}) — replayed the projection onto the "
                "new priors so the live table and a replay agree"
            )


if __name__ == "__main__":
    main()
