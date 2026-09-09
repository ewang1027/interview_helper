"""Re-tag practice-log problems, and correct the evidence the old tags wrote.

`PATCH /practice/problems/{id}/classification` refuses anything already resolved, and for
the right reason: the evidence is written, and `concept_evidence` is immutable. That
refusal protects mastery from a casual edit. It also means a problem tagged wrongly on the
day it was logged — `invert-binary-tree` as breadth-first search, `missing-number` as
binary search, both real — stays wrong, and its evidence keeps moving a concept it never
exercised.

This is the one sanctioned way to correct that, and it is a script rather than an endpoint
on purpose: it runs from a shell, against a database you have just backed up, with a dry
run first. docs/CONCEPTS.md says splitting a concept is a migration and that what happens
to existing evidence is decided in the same commit — this is that decision, made once, in
one place.

What it does, per problem in the mapping:

- **Still `pending_classification`** — resolves it through the ordinary path
  (`practice.resolve_classification`), which writes the evidence that was waiting.
- **Already resolved** — sets the new primary and secondaries on the problem, and
  re-points every evidence row that carried the *old primary* to the new one. The row's
  score, confidence and timestamp are untouched: the solve happened, at that time, with
  that certainty; only the concept it was credited to was wrong. Rows carrying an old
  secondary that the new tags drop are left alone and reported. New secondaries apply to
  the *next* solve; nothing is invented for a past one.

Then `mastery` is rebuilt from the corrected log, which is what a projection is for.

Usage:

    uv run python scripts/retag_practice_problems.py MAPPING.json [--dry-run]

`MAPPING.json` maps a LeetCode slug or problem URL to `{"primary": id, "secondaries":
[ids]}`. Every concept named must exist in `concepts.json` *and* in the database — run
`make seed` after changing the taxonomy, or the foreign key refuses the update.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlmodel import Session, select

from api import practice
from api.db import get_engine
from api.mastery import recompute
from api.models import Concept, ConceptEvidence, PracticeProblem
from api.users import single_user


def _load_mapping(path: Path) -> dict[str, tuple[str, tuple[str, ...]]]:
    raw = json.loads(path.read_text())
    mapping: dict[str, tuple[str, tuple[str, ...]]] = {}
    for key, value in raw.items():
        primary = value["primary"]
        secondaries = tuple(c for c in value.get("secondaries", ()) if c != primary)
        mapping[practice.same_problem_key(key)] = (primary, secondaries)
    return mapping


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("mapping", type=Path)
    parser.add_argument("--dry-run", action="store_true", help="report the plan, write nothing")
    args = parser.parse_args(argv)

    mapping = _load_mapping(args.mapping)
    wanted = {c for primary, secondaries in mapping.values() for c in (primary, *secondaries)}
    unknown = sorted(wanted - practice.concept_ids())
    if unknown:
        print(f"not in concepts.json: {unknown}", file=sys.stderr)
        return 2

    with Session(get_engine()) as db:
        unseeded = sorted(c for c in wanted if db.get(Concept, c) is None)
        if unseeded:
            print(f"not in the database — run `make seed` first: {unseeded}", file=sys.stderr)
            return 2

        user = single_user(db)
        rows = db.exec(select(PracticeProblem)).all()
        by_key = {practice.same_problem_key(row.url): row for row in rows}
        missing = sorted(set(mapping) - set(by_key))
        if missing:
            print(f"no logged problem matches: {missing}", file=sys.stderr)
            return 2

        repointed = 0
        resolved = 0
        for key, (primary, secondaries) in mapping.items():
            row = by_key[key]
            old_primary, old_secondaries = row.primary_concept_id, list(row.secondary_concept_ids)
            if old_primary == primary and old_secondaries == list(secondaries):
                print(f"= {row.title}: already {primary} {list(secondaries)}")
                continue

            if row.status == "pending_classification":
                print(f"+ {row.title}: pending -> {primary} {list(secondaries)} (writes evidence)")
                if not args.dry_run:
                    practice.resolve_classification(
                        db,
                        row.id,
                        user_id=user.id,
                        primary_concept_id=primary,
                        secondary_concept_ids=secondaries,
                    )
                resolved += 1
                continue

            evidence = db.exec(
                select(ConceptEvidence).where(ConceptEvidence.practice_problem_id == row.id)
            ).all()
            moved = [e for e in evidence if e.concept_id == old_primary and old_primary != primary]
            orphaned = [
                e
                for e in evidence
                if e.concept_id != old_primary and e.concept_id not in (primary, *secondaries)
            ]
            print(
                f"~ {row.title}: {old_primary} {old_secondaries} -> {primary} {list(secondaries)}; "
                f"{len(moved)} evidence row(s) re-pointed"
                + (f", {len(orphaned)} left on a dropped secondary" if orphaned else "")
            )
            if args.dry_run:
                continue
            row.primary_concept_id = primary
            row.secondary_concept_ids = list(secondaries)
            row.updated_at = datetime.now(UTC)
            db.add(row)
            for e in moved:
                e.concept_id = primary
                db.add(e)
            repointed += len(moved)

        if args.dry_run:
            db.rollback()
            print("dry run — nothing written")
            return 0

        db.commit()
        result = recompute(db, user.id)
        print(
            f"resolved {resolved} pending problem(s), re-pointed {repointed} evidence row(s); "
            f"mastery rebuilt from {result['evidence_replayed']} rows "
            f"over {result['concepts']} concepts"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
