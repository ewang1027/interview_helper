"""The practice log: problems you solved elsewhere, folded into the same mastery.

docs/PRACTICE_LOG.md is the specification and this is its behaviour. Three things about it
are worth stating before the code, because each is a decision rather than a mechanism:

1. **A logged solve is evidence, not a second kind of evidence.** It writes an ordinary
   `concept_evidence` row and moves the same `mastery` projection a graded submission does.
   A parallel table would have been easier and would have defeated the point — the value of
   logging an external problem is that it counts.

2. **Nothing is written against a guess.** The classification call proposes concepts, and
   `concept_evidence` is immutable, so evidence written against a bad tag could never be
   retracted without an amendment mechanism this design does not have. Below the confidence
   gate the problem sits in `pending_classification`: visible, out of the review queue, and
   feeding nothing until it is confirmed or corrected. The short pending state is the price
   of never needing a tombstone.

3. **The schedule is a projection over the solve log**, exactly as `mastery` is a
   projection over evidence. `solve_count`, `stability_days` and `due_at` are derived from
   `practice_solves` and can be rebuilt from it; the log is what actually happened.

Scheduling is FSRS-*inspired* and deliberately not FSRS: three solves and a problem
graduates, so `stability_days` here means "the current interval", not a memory strength.
The constants are placeholders, like every other constant in this project until real usage
exists to tune them against.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

from sqlmodel import Session, col, select

from api import llm
from api.errors import ProblemError, not_found, unprocessable, wrong_state
from api.grading.coding import SECONDARY_CONFIDENCE
from api.mastery import apply_evidence, as_utc, lock_projection
from api.models import ConceptEvidence, PracticeProblem, PracticeSolve
from api.settings import Settings
from corpus.loader import load_concepts

logger = logging.getLogger(__name__)

# Recorded on every row this writes, as a grader version is, so a constant change below
# leaves old evidence interpretable rather than silently re-meaning it.
SCHEDULER_VERSION = "practice-log-v1"

SOURCE = "practice_log"

# docs/PRACTICE_LOG.md's placeholders. An SM-2-style ease, a first interval short enough to
# catch a solve that did not stick, and a lapse that halves rather than resets — a problem
# you missed on review is not a problem you never solved.
INITIAL_INTERVAL_DAYS = 3.0
GROWTH_FACTOR = 2.5
LAPSE_SHRINK = 0.5
MIN_INTERVAL_DAYS = 1.0

# Three solves and it graduates. The cap is why this is not full FSRS: there is no long tail
# to model, so there is no memory model to fit.
GRADUATION_SOLVES = 3

# Below this, the classification is a proposal rather than a tag, and nothing is written.
AUTO_ACCEPT_CONFIDENCE = 0.75

# What a self-reported solve is worth. Above a rubric judgement's 0.5, because it is a fact
# about a real solve rather than a model's read of prose — and well below a hidden test's
# 0.9, because nothing checked it. A failed re-solve is softer still: forgetting a problem
# is weaker evidence of not knowing a concept than failing a test on it is, so it says a
# little, at 0.2, quietly.
SOLVE_SCORE = 1.0
SOLVE_CONFIDENCE = 0.7
LAPSE_SCORE = 0.2
LAPSE_CONFIDENCE = 0.5

# Enough for a classification with a short reason. The reason is a paraphrase, never the
# problem's text — docs/PRACTICE_LOG.md's rule that this system stores pointers, not content.
MAX_TOKENS = 1024

SYSTEM_PROMPT = """You are tagging a programming or quantitative problem that someone has
just solved, against a fixed taxonomy of concepts. You are given only the problem's title,
its URL and whatever notes the solver wrote — never the problem statement, and you must not
reconstruct or quote one.

Choose the single concept the problem is *chiefly* an exercise in as `primary_concept_id`,
and up to four others it genuinely also exercises as `secondary_concept_ids`. Fewer is
better: a list of everything the problem touches is a list that says nothing.

`confidence` is how sure you are of the primary tag specifically. Be honest and be willing
to be low — below the threshold this application will ask a human rather than record your
guess, which is the outcome you want when a title is all you have. A title like "Two Sum"
is unambiguous; one like "Problem C" is not, whatever the URL suggests.

`reasoning` is one sentence, in your own words, naming what makes the primary tag right.

The taxonomy follows."""


@dataclass(frozen=True)
class Classification:
    """What the model proposed, and whether it was sure enough to act on."""

    primary_concept_id: str | None
    secondary_concept_ids: tuple[str, ...]
    confidence: float
    reasoning: str
    model: str | None

    @property
    def auto_accepted(self) -> bool:
        return self.primary_concept_id is not None and self.confidence >= AUTO_ACCEPT_CONFIDENCE


@lru_cache
def _concepts() -> tuple[Any, ...]:
    """The taxonomy is a build-time artifact and cannot change under a running process."""
    return tuple(load_concepts())


def concept_ids() -> frozenset[str]:
    return frozenset(concept.id for concept in _concepts())


def taxonomy_prompt() -> str:
    """The 159 concepts, one line each, above the cache breakpoint.

    docs/COST.md's cache shape: this block changes only when the corpus version bumps, and
    the per-problem details go in the message below it. `api.llm` marks the system block
    cacheable, so the taxonomy is written once and read on every later call.
    """
    lines = [f"{concept.id} ({concept.domain}) — {concept.description}" for concept in _concepts()]
    return f"{SYSTEM_PROMPT}\n\n" + "\n".join(lines)


def response_schema() -> dict[str, Any]:
    """`primary_concept_id` is an enum of the taxonomy's own ids.

    Same reason the rubric grader enumerates an item's criteria: a tag that is not a concept
    cannot be expressed rather than having to be caught afterwards — and `concept_evidence`
    keys on a foreign key, so the alternative failure is an insert error.
    """
    ids = sorted(concept_ids())
    return {
        "type": "object",
        "properties": {
            "primary_concept_id": {"type": "string", "enum": ids},
            "secondary_concept_ids": {
                "type": "array",
                "maxItems": 4,
                "items": {"type": "string", "enum": ids},
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "reasoning": {"type": "string"},
        },
        "required": ["primary_concept_id", "secondary_concept_ids", "confidence", "reasoning"],
        "additionalProperties": False,
    }


def build_prompt(*, title: str, url: str, notes: str | None, difficulty_label: str | None) -> str:
    lines = [f"Title: {title}", f"URL: {url}"]
    if difficulty_label:
        lines.append(f"Difficulty label given by the site: {difficulty_label}")
    if notes:
        lines.append(f"The solver's own notes: {notes}")
    return "\n".join(lines)


def classify(
    *,
    title: str,
    url: str,
    notes: str | None = None,
    difficulty_label: str | None = None,
    client: Any = None,
    settings: Settings | None = None,
) -> Classification:
    """Propose concepts for one problem. Never raises.

    A provider that is down should not lose someone's log entry. The problem is recorded
    either way and lands in `pending_classification` with nothing proposed, which is a state
    the flow already has and a human already resolves — so the failure costs a confirmation
    rather than the entry.
    """
    try:
        completion = llm.complete(
            job="practice_log_classify",
            system=taxonomy_prompt(),
            messages=[
                {
                    "role": "user",
                    "content": build_prompt(
                        title=title, url=url, notes=notes, difficulty_label=difficulty_label
                    ),
                }
            ],
            max_tokens=MAX_TOKENS,
            output_schema=response_schema(),
            client=client,
            settings=settings,
        )
    except ProblemError as exc:
        logger.warning("classification unavailable, logging unclassified: %s", exc.detail)
        return Classification(None, (), 0.0, f"classification unavailable: {exc.detail}", None)
    except Exception as exc:
        # Broader than the errors `api.llm` maps, and deliberately: the contract of this
        # function is that a classification failure costs a confirmation, never the log
        # entry. A raw provider or wiring error escaping here would make that false in
        # exactly the situation it exists for. Logged with a traceback so a bug in here
        # is visible rather than quietly becoming a pending problem forever.
        logger.exception("classification failed, logging unclassified")
        return Classification(None, (), 0.0, f"classification failed: {type(exc).__name__}", None)

    try:
        payload = json.loads(completion.text)
    except ValueError:
        logger.warning("classifier did not answer with JSON: %r", completion.text[:200])
        return Classification(None, (), 0.0, "the classifier did not answer with JSON", None)

    known = concept_ids()
    primary = payload.get("primary_concept_id")
    if primary not in known:
        return Classification(None, (), 0.0, f"proposed unknown concept {primary!r}", None)
    secondaries = tuple(
        cid
        for cid in payload.get("secondary_concept_ids") or []
        # The primary is not also a secondary: it would write the same concept twice from
        # one solve, at two confidences, which overstates one problem as two readings.
        if cid in known and cid != primary
    )
    return Classification(
        primary_concept_id=primary,
        secondary_concept_ids=secondaries,
        confidence=max(0.0, min(1.0, float(payload.get("confidence", 0.0)))),
        reasoning=str(payload.get("reasoning", "")),
        model=completion.model,
    )


# --- Scheduling -----------------------------------------------------------------------------


def first_interval(solved_at: datetime) -> tuple[float, datetime]:
    return INITIAL_INTERVAL_DAYS, solved_at + timedelta(days=INITIAL_INTERVAL_DAYS)


def next_interval(stability_days: float, *, success: bool) -> float:
    """The interval after one review.

    A lapse halves rather than resets: a problem you missed on review is not a problem you
    never solved, and sending it back to three days would treat those the same."""
    if success:
        return stability_days * GROWTH_FACTOR
    return max(MIN_INTERVAL_DAYS, stability_days * LAPSE_SHRINK)


# --- Writing evidence -----------------------------------------------------------------------


def evidence_rows(problem: PracticeProblem, *, success: bool) -> list[tuple[str, float, float]]:
    """`(concept_id, score, confidence)` for one solve.

    The primary concept carries the full claim and the secondaries a fraction of it, the
    same split and the same constant the coding grader uses — a problem is chiefly an
    exercise in one thing, and really does exercise the others.
    """
    if problem.primary_concept_id is None:
        return []
    score = SOLVE_SCORE if success else LAPSE_SCORE
    confidence = SOLVE_CONFIDENCE if success else LAPSE_CONFIDENCE
    rows = [(problem.primary_concept_id, score, confidence)]
    rows += [
        (concept_id, score, round(confidence * SECONDARY_CONFIDENCE, 4))
        for concept_id in problem.secondary_concept_ids
    ]
    return rows


def _write_evidence(
    db: Session, problem: PracticeProblem, solve: PracticeSolve, *, user_id: str, success: bool
) -> list[ConceptEvidence]:
    """Fold one solve into the shared projection.

    `item_id` and `session_id` stay null and `practice_problem_id` is set — the CHECK
    constraint requires exactly one of the two, and `apply_evidence` reads an item-less row
    as "we do not know how hard this was" and scores it against the candidate's own current
    ability rather than inventing a difficulty for it.
    """
    lock_projection(db)
    written: list[ConceptEvidence] = []
    for concept_id, score, confidence in evidence_rows(problem, success=success):
        row = ConceptEvidence(
            concept_id=concept_id,
            source=SOURCE,
            practice_problem_id=problem.id,
            score=score,
            confidence=confidence,
            grader_version=SCHEDULER_VERSION,
        )
        db.add(row)
        written.append(row)
    db.flush()
    for row in written:
        apply_evidence(db, row, user_id=user_id)
    if written and solve.concept_evidence_id is None:
        # The one field on an append-only row that is ever filled in later, and only for a
        # solve logged before its classification was resolved. It is a pointer, not the
        # record: what the row says happened — a solve, at this time, successfully — is
        # never rewritten.
        solve.concept_evidence_id = written[0].id
        db.add(solve)
    return written


# --- The flows ------------------------------------------------------------------------------


def log_problem(
    db: Session,
    *,
    user_id: str,
    title: str,
    url: str,
    source_site: str,
    notes: str | None = None,
    difficulty_label: str | None = None,
    solved_at: datetime | None = None,
    client: Any = None,
    settings: Settings | None = None,
) -> PracticeProblem:
    """Log a problem you solved, classify it, and — if the tag is sure enough — count it."""
    solved = as_utc(solved_at or datetime.now(UTC))
    proposed = classify(
        title=title,
        url=url,
        notes=notes,
        difficulty_label=difficulty_label,
        client=client,
        settings=settings,
    )
    stability, due = first_interval(solved)
    problem = PracticeProblem(
        title=title,
        url=url,
        source_site=source_site,
        notes=notes,
        difficulty_label=difficulty_label,
        primary_concept_id=proposed.primary_concept_id,
        secondary_concept_ids=list(proposed.secondary_concept_ids),
        classification_confidence=proposed.confidence,
        classification_model=proposed.model,
        status="active" if proposed.auto_accepted else "pending_classification",
        solve_count=1,
        # A pending problem is out of the review queue, so it carries no schedule until its
        # classification resolves — a due date on something that feeds nothing is a prompt
        # to re-solve a problem the system cannot record you having re-solved.
        stability_days=stability if proposed.auto_accepted else None,
        due_at=due if proposed.auto_accepted else None,
    )
    db.add(problem)
    db.flush()

    solve = PracticeSolve(
        problem_id=problem.id,
        review_number=0,
        is_success=True,  # you only log a problem you solved
        attempted_at=solved,
        notes=notes,
    )
    db.add(solve)
    db.flush()

    if proposed.auto_accepted:
        _write_evidence(db, problem, solve, user_id=user_id, success=True)
    db.commit()
    db.refresh(problem)
    return problem


def resolve_classification(
    db: Session,
    problem_id: str,
    *,
    user_id: str,
    primary_concept_id: str,
    secondary_concept_ids: tuple[str, ...] = (),
) -> PracticeProblem:
    """Confirm or correct a proposed classification, and write the evidence that waited."""
    problem = db.get(PracticeProblem, problem_id)
    if problem is None:
        raise not_found("practice problem", problem_id)
    if problem.status != "pending_classification":
        raise wrong_state(
            f"Problem is {problem.status!r}; only a pending classification can be resolved. "
            "Its evidence is already written, and evidence is immutable.",
            state=problem.status,
        )
    known = concept_ids()
    unknown = [c for c in (primary_concept_id, *secondary_concept_ids) if c not in known]
    if unknown:
        raise unprocessable(f"Not concepts in this project's taxonomy: {sorted(set(unknown))}.")

    solve = db.exec(
        select(PracticeSolve)
        .where(PracticeSolve.problem_id == problem.id)
        .order_by(col(PracticeSolve.review_number))
    ).first()
    if solve is None:  # pragma: no cover - a problem always has its initial solve
        raise wrong_state("Problem has no logged solve.", state=problem.status)

    problem.primary_concept_id = primary_concept_id
    problem.secondary_concept_ids = [c for c in secondary_concept_ids if c != primary_concept_id]
    problem.status = "active"
    stability, due = first_interval(as_utc(solve.attempted_at))
    problem.stability_days = stability
    problem.due_at = due
    problem.updated_at = datetime.now(UTC)
    db.add(problem)
    db.flush()

    _write_evidence(db, problem, solve, user_id=user_id, success=True)
    db.commit()
    db.refresh(problem)
    return problem


def record_review(
    db: Session,
    problem_id: str,
    *,
    user_id: str,
    is_success: bool,
    notes: str | None = None,
    attempted_at: datetime | None = None,
) -> PracticeProblem:
    """Record a scheduled re-solve, and move the problem's schedule accordingly."""
    problem = db.get(PracticeProblem, problem_id)
    if problem is None:
        raise not_found("practice problem", problem_id)
    if problem.status != "active":
        raise wrong_state(
            f"Problem is {problem.status!r}; reviews are recorded against an active one.",
            state=problem.status,
        )
    when = as_utc(attempted_at or datetime.now(UTC))
    reviews = db.exec(select(PracticeSolve).where(PracticeSolve.problem_id == problem.id)).all()
    solve = PracticeSolve(
        problem_id=problem.id,
        review_number=len(reviews),
        is_success=is_success,
        attempted_at=when,
        notes=notes,
    )
    db.add(solve)
    db.flush()

    stability = problem.stability_days or INITIAL_INTERVAL_DAYS
    if is_success:
        # A failed attempt is not a solve, so only a success advances the count — which is
        # what makes "three solves and it graduates" mean three solves.
        problem.solve_count += 1
        if problem.solve_count >= GRADUATION_SOLVES:
            problem.status = "graduated"
            problem.due_at = None
            problem.graduated_at = when
        else:
            problem.stability_days = next_interval(stability, success=True)
            problem.due_at = when + timedelta(days=problem.stability_days)
    else:
        problem.stability_days = next_interval(stability, success=False)
        problem.due_at = when + timedelta(days=problem.stability_days)
    problem.updated_at = datetime.now(UTC)
    db.add(problem)
    db.flush()

    _write_evidence(db, problem, solve, user_id=user_id, success=is_success)
    db.commit()
    db.refresh(problem)
    return problem


# --- Reads ----------------------------------------------------------------------------------


def as_view(problem: PracticeProblem) -> dict[str, Any]:
    """One problem, as the API returns it."""
    return {
        "id": problem.id,
        "title": problem.title,
        "url": problem.url,
        "source_site": problem.source_site,
        "notes": problem.notes,
        "difficulty_label": problem.difficulty_label,
        "primary_concept_id": problem.primary_concept_id,
        "secondary_concept_ids": list(problem.secondary_concept_ids),
        "classification": {
            "confidence": problem.classification_confidence,
            "model": problem.classification_model,
            "auto_accepted": problem.status != "pending_classification",
        },
        "status": problem.status,
        "solve_count": problem.solve_count,
        "stability_days": problem.stability_days,
        "due_at": problem.due_at,
        "graduated_at": problem.graduated_at,
        "created_at": problem.created_at,
    }


def list_problems(
    db: Session,
    *,
    concept_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Newest first, cursor-paginated on the ULID — which sorts by creation time already."""
    query = select(PracticeProblem)
    if status is not None:
        query = query.where(col(PracticeProblem.status) == status)
    if cursor is not None:
        query = query.where(col(PracticeProblem.id) < cursor)
    rows = list(db.exec(query.order_by(col(PracticeProblem.id).desc()).limit(limit + 1)).all())
    if concept_id is not None:
        # Filtered here rather than in SQL: the secondary ids are a JSONB array, and a
        # containment query over it would need a GIN index this table has no need for at
        # the scale it will ever reach.
        rows = [
            row
            for row in rows
            if row.primary_concept_id == concept_id or concept_id in row.secondary_concept_ids
        ]
    more = len(rows) > limit
    rows = rows[:limit]
    return {
        "problems": [as_view(row) for row in rows],
        "next_cursor": rows[-1].id if more and rows else None,
    }


def review_queue(db: Session, *, now: datetime | None = None) -> dict[str, Any]:
    """What is due, most overdue first.

    `active` only, so a problem whose classification is still a proposal cannot prompt a
    re-solve the system would then be unable to record.
    """
    moment = as_utc(now or datetime.now(UTC))
    rows = db.exec(
        select(PracticeProblem)
        .where(col(PracticeProblem.status) == "active")
        .where(col(PracticeProblem.due_at) <= moment)
        .order_by(col(PracticeProblem.due_at))
    ).all()
    return {
        "as_of": moment,
        "due": [
            {**as_view(row), "days_overdue": round((moment - as_utc(row.due_at)).days, 2)}
            for row in rows
            if row.due_at is not None
        ],
    }


def problem_detail(db: Session, problem_id: str) -> dict[str, Any]:
    """A problem, its whole solve history, and the evidence those solves produced."""
    problem = db.get(PracticeProblem, problem_id)
    if problem is None:
        raise not_found("practice problem", problem_id)
    solves = db.exec(
        select(PracticeSolve)
        .where(PracticeSolve.problem_id == problem.id)
        .order_by(col(PracticeSolve.review_number))
    ).all()
    evidence = db.exec(
        select(ConceptEvidence)
        .where(col(ConceptEvidence.practice_problem_id) == problem.id)
        .order_by(col(ConceptEvidence.id))
    ).all()
    return {
        **as_view(problem),
        "solves": [
            {
                "review_number": row.review_number,
                "is_success": row.is_success,
                "attempted_at": row.attempted_at,
                "notes": row.notes,
                "concept_evidence_id": row.concept_evidence_id,
            }
            for row in solves
        ],
        "evidence": [
            {
                "concept_id": row.concept_id,
                "score": row.score,
                "confidence": row.confidence,
                "grader_version": row.grader_version,
                "ts": row.ts,
            }
            for row in evidence
        ],
    }
