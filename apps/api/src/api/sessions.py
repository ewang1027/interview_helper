"""The session lifecycle: plan it, take a submission, grade it, write the evidence.

This is the first code in the project that *writes user data*, and the first that turns a
grade into rows in Postgres. Three rules from the specs are load-bearing here:

- **A failed grading is recorded, never scored.** `gradings.status` says what happened and
  `score` stays NULL. No `concept_evidence` row is written for it, because a fabricated
  score corrupts mastery permanently and a missing one is merely visible (GRADING.md).
- **`abandoned` keeps whatever was graded.** Ending a session early does not retract
  evidence — a session you quit halfway through is real data about the half you did
  (API.md).
- **Evidence is append-only.** Nothing here updates or deletes a `concept_evidence` row;
  a grader fix is applied by re-running the grader over the stored artifact, which is why
  `api.grading` never touches the database itself (ADAPTIVE.md).

What is deliberately absent: the interviewer agent, so no `turns` are written and no
model is called; the SSE stream, so state changes are observed by polling
`GET /sessions/{id}`; and auth, so `current_user` returns the single local user.
"""

from __future__ import annotations

from datetime import UTC, datetime
from functools import lru_cache
from typing import Any, Literal

from sqlmodel import Session, col, select

from api.db import get_engine
from api.errors import not_found, unavailable, unprocessable, wrong_state
from api.executor_client import (
    CodeRunner,
    ExecutorProtocolError,
    ExecutorUnavailableError,
    Language,
)
from api.grading.coding import GRADER_VERSION, CodingGrade, grade_coding
from api.mastery import apply_evidence
from api.models import Artifact, ConceptEvidence, Grading, InterviewSession, Item
from api.planner import build_plan, plan_item_ids
from api.users import current_user
from corpus.loader import load_items
from corpus.models import Item as CorpusItem

# The spec's vocabulary in full (docs/API.md). Implemented today: planning -> briefing on
# creation, briefing -> interviewing on the first submission, -> complete when every
# planned item has a terminal grading, and -> abandoned from `POST /end`. `wrapping` and
# `grading` are the agent's and the rubric graders' states; nothing can observe them yet,
# and inventing transitions through them would be theatre.
SessionState = Literal[
    "planning",
    "briefing",
    "interviewing",
    "wrapping",
    "grading",
    "complete",
    "abandoned",
    "failed",
]

OPEN_STATES = frozenset({"briefing", "interviewing"})
REPORTABLE_STATES = frozenset({"complete", "abandoned"})

# Modes with a grader that exists. Creating a session in a mode nothing can grade would
# produce an interview that can never complete, so it is refused with the reason rather
# than allowed and then dead-ended at submission time. Widens as graders land.
GRADEABLE_MODES = frozenset({"coding"})

# The languages the executor will accept, as a narrowing table: `artifacts.language` is
# a free string in the database, and handing an unknown one straight to the grader would
# be a type error waiting for the first hand-written row.
LANGUAGES: dict[str, Language] = {"python": "python", "cpp": "cpp"}

# What a submission of each kind is called. Only `code` has a grader today.
MODE_ARTIFACT_KIND = {
    "coding": "code",
    "quant": "answer",
    "design": "design",
    "behavioral": "narrative",
}


@lru_cache
def _corpus_index() -> dict[str, CorpusItem]:
    """The corpus is a build-time artifact and cannot change under a running process."""
    return {item.id: item for item in load_items()}


def corpus_item(item_id: str) -> CorpusItem | None:
    return _corpus_index().get(item_id)


def _now() -> datetime:
    return datetime.now(UTC)


# --- Creating and reading sessions ----------------------------------------------------


def create_session(
    db: Session,
    *,
    mode: str,
    budget_minutes: int,
    focus_concepts: tuple[str, ...] = (),
    difficulty_bias: float = 0.0,
) -> InterviewSession:
    if mode not in GRADEABLE_MODES:
        raise unprocessable(
            f"No grader exists for {mode!r} yet, so a {mode} session could never be graded "
            f"or completed. Gradeable today: {sorted(GRADEABLE_MODES)}.",
            mode=mode,
        )

    plan = build_plan(
        mode,
        budget_minutes,
        focus_concepts=focus_concepts,
        difficulty_bias=difficulty_bias,
    )
    item_ids = plan_item_ids(plan)
    if not item_ids:
        raise unprocessable(
            f"The corpus has no active {mode} instances matching this request.",
            focus_concepts=list(focus_concepts),
        )

    # The corpus is the source of truth and the `items` table is a projection of it, so a
    # plan can name an item the database has never been told about. Say that in a sentence
    # instead of letting it surface as a foreign-key violation three calls later.
    seeded = set(db.exec(select(Item.id).where(col(Item.id).in_(item_ids))).all())
    missing = [item_id for item_id in item_ids if item_id not in seeded]
    if missing:
        raise unavailable(
            f"The corpus is not seeded into the database: {missing[:3]} missing. Run `make seed`."
        )

    session_row = InterviewSession(
        user_id=current_user(db).id,
        mode=mode,
        budget_minutes=budget_minutes,
        status="briefing",
        plan=plan,
    )
    db.add(session_row)
    db.commit()
    db.refresh(session_row)
    return session_row


def get_session(db: Session, session_id: str) -> InterviewSession:
    session_row = db.get(InterviewSession, session_id)
    if session_row is None:
        raise not_found("session", session_id)
    return session_row


def list_sessions(
    db: Session, *, cursor: str | None = None, limit: int = 20
) -> list[InterviewSession]:
    """Newest first, cursor-paginated. ULIDs sort by creation time, so the id *is* the
    cursor — offsets drift when rows are inserted under you (docs/API.md)."""
    query = select(InterviewSession).order_by(col(InterviewSession.id).desc()).limit(limit)
    if cursor:
        query = query.where(col(InterviewSession.id) < cursor)
    return list(db.exec(query).all())


# --- Submissions ----------------------------------------------------------------------


def record_submission(
    db: Session,
    session_row: InterviewSession,
    *,
    item_id: str,
    kind: str,
    content: str,
    language: str | None = None,
    elapsed_seconds: int = 0,
) -> Artifact:
    """Store what the candidate submitted. Grading happens after, out of the request."""
    if session_row.status not in OPEN_STATES:
        raise wrong_state(
            f"Session is {session_row.status!r}; submissions are only accepted while it is "
            f"one of {sorted(OPEN_STATES)}.",
            state=session_row.status,
        )

    if item_id not in plan_item_ids(session_row.plan):
        raise unprocessable(
            f"{item_id!r} is not in this session's plan.",
            item_id=item_id,
            plan=plan_item_ids(session_row.plan),
        )

    expected_kind = MODE_ARTIFACT_KIND[session_row.mode]
    if kind != expected_kind:
        raise unprocessable(f"A {session_row.mode} session takes {expected_kind!r}, not {kind!r}.")

    item = corpus_item(item_id)
    if item is None:  # pragma: no cover - the plan is built from the same corpus
        raise not_found("item", item_id)

    declared = (item.grading or {}).get("languages") or []
    language = language or (declared[0] if declared else None)
    if kind == "code" and language not in declared:
        raise unprocessable(
            f"{item_id} accepts {declared}, not {language!r}.", languages=list(declared)
        )

    existing = db.exec(
        select(Artifact).where(Artifact.session_id == session_row.id, Artifact.item_id == item_id)
    ).first()
    if existing is not None:
        # Not idempotency — the client cannot tell a retry from a genuine second attempt
        # here — but it does refuse the harmful half of the missing `Idempotency-Key`
        # support: one item cannot write two sets of evidence into one session. Iterating
        # on a submission is the interviewer loop's job, and that does not exist yet.
        raise wrong_state(
            f"{item_id} already has a submission in this session.", artifact_id=existing.id
        )

    artifact = Artifact(
        session_id=session_row.id,
        item_id=item_id,
        kind=kind,
        language=language,
        content=content,
        elapsed_seconds=elapsed_seconds,
    )
    db.add(artifact)
    if session_row.status == "briefing":
        session_row.status = "interviewing"
        db.add(session_row)
    db.commit()
    db.refresh(artifact)
    return artifact


# --- Grading --------------------------------------------------------------------------


def grade_artifact(artifact_id: str, runner: CodeRunner | None = None) -> None:
    """Grade one stored submission and write what it implies.

    Runs *outside* the request (a coding grade with a complexity probe takes tens of
    seconds — docs/API.md returns 202 for exactly this reason), so it opens its own
    database session rather than borrowing a closed one.

    Never raises: a caller with nothing to return the error to would only lose it. Every
    failure path ends in a `gradings` row that says what went wrong.
    """
    with Session(get_engine()) as db:
        artifact = db.get(Artifact, artifact_id)
        if artifact is None:  # pragma: no cover - only reachable if the row was deleted
            return
        item = corpus_item(artifact.item_id)
        if item is None:
            _record_failure(db, artifact, f"{artifact.item_id} is not in this build's corpus")
            return

        language = LANGUAGES.get(artifact.language or "python")
        if language is None:
            _record_failure(
                db, artifact, f"{artifact.language!r} is not a language the executor runs"
            )
            return

        try:
            grade = grade_coding(item, artifact.content, runner=runner, language=language)
        except ExecutorUnavailableError as exc:
            # The submission is not at fault and must not be scored for it. The artifact
            # stays on disk, so re-running the grader later is all it takes.
            _record_failure(db, artifact, f"executor unavailable: {exc}")
            return
        except (ExecutorProtocolError, ValueError) as exc:
            _record_failure(db, artifact, f"grader refused this submission: {exc}")
            return

        _record_grade(db, artifact, grade)


def _record_failure(db: Session, artifact: Artifact, detail: str) -> None:
    db.add(
        Grading(
            artifact_id=artifact.id,
            status="failed",
            score=None,
            detail={"status": "failed", "detail": detail},
            grader_version=GRADER_VERSION,
        )
    )
    db.commit()
    _maybe_complete(db, artifact.session_id)


def _record_grade(db: Session, artifact: Artifact, grade: CodingGrade) -> None:
    db.add(
        Grading(
            artifact_id=artifact.id,
            status=grade.status,
            score=grade.score,
            detail=grade.as_detail(),
            grader_version=grade.grader_version,
        )
    )
    evidence = [
        ConceptEvidence(
            concept_id=row.concept_id,
            source="session_grading",
            item_id=artifact.item_id,
            session_id=artifact.session_id,
            score=row.score,
            confidence=row.confidence,
            grader_version=row.grader_version,
        )
        for row in grade.evidence
    ]
    for row in evidence:
        db.add(row)
    db.flush()

    # The projection is advanced in the same transaction that writes the evidence, so the
    # two can never disagree about what has been seen. It is still only a projection:
    # `POST /mastery/recompute` rebuilds it from these rows alone, and a db test asserts
    # the rebuild reproduces what this loop produced.
    session_row = db.get(InterviewSession, artifact.session_id)
    if session_row is not None:
        for row in evidence:
            apply_evidence(db, row, user_id=session_row.user_id)

    db.commit()
    _maybe_complete(db, artifact.session_id)


def _maybe_complete(db: Session, session_id: str) -> None:
    """A session is done when every planned item has reached a terminal grading.

    A *failed* grading is terminal too: nothing can be resubmitted for that item, so
    waiting for it would leave the session open forever. Such a session completes with
    less evidence than it has items, which is the honest outcome.
    """
    session_row = db.get(InterviewSession, session_id)
    if session_row is None or session_row.status not in OPEN_STATES:
        return
    outcomes = _item_outcomes(db, session_row)
    if all(entry["status"] in {"graded", "failed"} for entry in outcomes):
        session_row.status = "complete"
        session_row.ended_at = _now()
        db.add(session_row)
        db.commit()


# --- Ending, viewing, reporting -------------------------------------------------------


def end_session(db: Session, session_row: InterviewSession) -> InterviewSession:
    if session_row.status not in OPEN_STATES:
        raise wrong_state(f"Session is already {session_row.status!r}.", state=session_row.status)
    session_row.status = "abandoned"
    session_row.ended_at = _now()
    db.add(session_row)
    db.commit()
    db.refresh(session_row)
    return session_row


def _item_outcomes(db: Session, session_row: InterviewSession) -> list[dict[str, Any]]:
    """One row per planned item: what was submitted for it and how it was graded."""
    artifacts = {
        artifact.item_id: artifact
        for artifact in db.exec(select(Artifact).where(Artifact.session_id == session_row.id)).all()
    }
    outcomes: list[dict[str, Any]] = []
    for entry in (session_row.plan or {}).get("items", []):
        item_id = entry["item_id"]
        artifact = artifacts.get(item_id)
        row: dict[str, Any] = {
            "item_id": item_id,
            "title": entry.get("title"),
            "status": "not_attempted",
            "artifact_id": None,
            "score": None,
            "detail": None,
        }
        if artifact is not None:
            row["artifact_id"] = artifact.id
            row["status"] = "grading"
            grading = db.exec(
                select(Grading)
                .where(Grading.artifact_id == artifact.id)
                .order_by(col(Grading.id).desc())
            ).first()
            if grading is not None:
                row["status"] = grading.status
                row["score"] = grading.score
                row["detail"] = grading.detail
        outcomes.append(row)
    return outcomes


def session_view(db: Session, session_row: InterviewSession) -> dict[str, Any]:
    """What `GET /sessions/{id}` returns. Also the way a client learns that grading
    finished, until the SSE stream exists."""
    ended = session_row.ended_at or _now()
    return {
        "id": session_row.id,
        "mode": session_row.mode,
        "state": session_row.status,
        "budget_minutes": session_row.budget_minutes,
        "started_at": session_row.started_at,
        "ended_at": session_row.ended_at,
        "elapsed_seconds": int((ended - session_row.started_at).total_seconds()),
        "plan": session_row.plan,
        "items": _item_outcomes(db, session_row),
        # docs/COST.md's budgets are read into settings and enforced nowhere, and no model
        # call has ever been made. Reporting a consumed figure would imply a meter exists.
        "tokens_consumed": 0,
        "budget_enforced": False,
    }


def build_report(db: Session, session_row: InterviewSession) -> dict[str, Any]:
    if session_row.status not in REPORTABLE_STATES:
        raise wrong_state(
            f"Session is {session_row.status!r}; a report exists once it is "
            f"{sorted(REPORTABLE_STATES)}.",
            state=session_row.status,
        )

    outcomes = _item_outcomes(db, session_row)
    scored = [row["score"] for row in outcomes if row["status"] == "graded"]
    evidence = db.exec(
        select(ConceptEvidence)
        .where(ConceptEvidence.session_id == session_row.id)
        .order_by(col(ConceptEvidence.id))
    ).all()

    return {
        "session_id": session_row.id,
        "mode": session_row.mode,
        "state": session_row.status,
        "started_at": session_row.started_at,
        "ended_at": session_row.ended_at,
        "items": outcomes,
        "mean_score": sum(scored) / len(scored) if scored else None,
        "graded": len(scored),
        "failed": sum(1 for row in outcomes if row["status"] == "failed"),
        "not_attempted": sum(1 for row in outcomes if row["status"] == "not_attempted"),
        "evidence": [
            {
                "concept_id": row.concept_id,
                "score": row.score,
                "confidence": row.confidence,
                "item_id": row.item_id,
                "grader_version": row.grader_version,
            }
            for row in evidence
        ],
        # Stated in the payload, not just in the docs: a report that silently omitted the
        # rubric half would read as a complete assessment of a session it only half graded.
        "notes": [
            "Deterministic grading only — no rubric grader exists yet (docs/GRADING.md).",
            "No interviewer agent ran: there are no turns, hints or observations.",
        ],
    }
