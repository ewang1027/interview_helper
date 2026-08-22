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

Every function here takes the user id it works on rather than resolving one: since
auth landed, the caller is whoever the request's signed cookie says it is (`api.auth`),
and a service that looks up "the current user" would be a service that cannot be told it
is wrong.

What is deliberately absent: the interviewer agent, so no `turns` are written and no
model is called, and the SSE stream, so state changes are observed by polling
`GET /sessions/{id}`.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any, Literal

from sqlmodel import Session, col, select

from api import events as event_bus
from api.agent import loop as agent_loop
from api.db import get_engine
from api.errors import ProblemError, not_found, unavailable, unprocessable, wrong_state
from api.executor_client import (
    CodeRunner,
    ExecutorProtocolError,
    ExecutorUnavailableError,
    Language,
)
from api.grading.coding import GRADER_VERSION, CodingGrade, grade_coding
from api.grading.quant import QuantGrade, grade_quant
from api.grading.rubric import RubricGrade, grade_rubric
from api.mastery import apply_evidence, lock_projection
from api.models import Artifact, ConceptEvidence, Grading, InterviewSession, Item, Turn
from api.planner import build_plan, eligible_items, plan_item_ids
from corpus.loader import load_items
from corpus.models import Item as CorpusItem

# The spec's vocabulary in full (docs/API.md). Implemented today: planning -> briefing on
# creation, briefing -> interviewing on the first submission, -> complete when every
# planned item has a terminal grading, and -> abandoned from `POST /end`. `wrapping` and
# `grading` are the agent's and the rubric graders' states; nothing can observe them yet,
# and inventing transitions through them would be theatre.
LOGGER = logging.getLogger(__name__)

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
# States a session can still finish from. `wrapping` is included and that is not cosmetic:
# the interviewer ending the last round moves a session there, and grading of an already
# submitted item lands afterwards — without this, such a session waits for a completion
# that can never happen. Turns and submissions are still refused while wrapping.
COMPLETABLE_STATES = OPEN_STATES | {"wrapping"}
REPORTABLE_STATES = frozenset({"complete", "abandoned"})

# Modes with a grader that exists. Creating a session in a mode nothing can grade would
# produce an interview that can never complete, so it is refused with the reason rather
# than allowed and then dead-ended at submission time.
#
# `design` and `behavioral` joined when the rubric grader landed, and `quant` when its
# answer check did (2026-08-21). Every mode the API accepts now has a grader, so the
# refusal below has no subject left — it is kept because the next mode added will need it,
# and a test asserts the two sets have not drifted apart.
GRADEABLE_MODES = frozenset({"coding", "quant", "design", "behavioral"})

# The languages the executor will accept, as a narrowing table: `artifacts.language` is
# a free string in the database, and handing an unknown one straight to the grader would
# be a type error waiting for the first hand-written row.
LANGUAGES: dict[str, Language] = {"python": "python", "cpp": "cpp"}

# What a submission of each kind is called. All four have a grader.
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
    user_id: str,
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
        db,
        user_id,
        mode,
        budget_minutes,
        focus_concepts=focus_concepts,
        difficulty_bias=difficulty_bias,
    )
    item_ids = plan_item_ids(plan)
    if not item_ids:
        # Two different emptinesses, and saying "no items match" for the second one sends
        # you looking for a corpus problem that is not there: an item is *served* for the
        # concept it is chiefly a measurement of, so focusing on a concept that only ever
        # appears as a secondary matches items and still plans nothing.
        detail = f"The corpus has no active {mode} instances matching this request."
        if focus_concepts and eligible_items(mode, focus_concepts):
            detail = (
                f"{list(focus_concepts)} appear only as secondary concepts on {mode} items. "
                "A session is planned around the concept an item chiefly measures."
            )
        raise unprocessable(detail, focus_concepts=list(focus_concepts))

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
        user_id=user_id,
        mode=mode,
        budget_minutes=budget_minutes,
        status="briefing",
        plan=plan,
    )
    db.add(session_row)
    db.commit()
    db.refresh(session_row)
    return session_row


def get_session(db: Session, session_id: str, *, user_id: str) -> InterviewSession:
    """One of this user's sessions, or 404.

    Someone else's id answers 404 rather than 403, which is the same answer a made-up id
    gets: a 403 would confirm the session exists. Multi-tenancy is still out of scope
    (docs/ARCHITECTURE.md) — this is only the query being scoped the way every mastery
    query already is, so that no route reads a row the caller does not own."""
    session_row = db.get(InterviewSession, session_id)
    if session_row is None or session_row.user_id != user_id:
        raise not_found("session", session_id)
    return session_row


def list_sessions(
    db: Session, *, user_id: str, cursor: str | None = None, limit: int = 20
) -> list[InterviewSession]:
    """Newest first, cursor-paginated. ULIDs sort by creation time, so the id *is* the
    cursor — offsets drift when rows are inserted under you (docs/API.md)."""
    query = (
        select(InterviewSession)
        .where(InterviewSession.user_id == user_id)
        .order_by(col(InterviewSession.id).desc())
        .limit(limit)
    )
    if cursor:
        query = query.where(col(InterviewSession.id) < cursor)
    return list(db.exec(query).all())


# --- Turns ------------------------------------------------------------------------------


def current_item(db: Session, session_row: InterviewSession) -> CorpusItem | None:
    """The planned item the interview is on, or None when every one is finished.

    Derived rather than stored: an item is finished when it has a submission or when the
    interviewer called `end_round` on it, and both of those are already recorded. A
    `current_item_id` column would be a third place for the same fact to live, and the
    first to go stale.
    """
    submitted = {
        artifact.item_id
        for artifact in db.exec(select(Artifact).where(Artifact.session_id == session_row.id)).all()
    }
    ended = {
        row.tool_calls["item_id"]
        for row in db.exec(select(Turn).where(Turn.session_id == session_row.id)).all()
        if row.tool_calls
        and row.tool_calls.get("tool") == "end_round"
        and not row.tool_calls.get("is_error")
        and row.tool_calls.get("item_id")
    }
    for item_id in plan_item_ids(session_row.plan):
        if item_id not in submitted and item_id not in ended:
            item = corpus_item(item_id)
            if item is not None:
                return item
    return None


def take_turn(
    db: Session,
    session_row: InterviewSession,
    content: str,
    *,
    runner: CodeRunner | None = None,
    client: Any = None,
) -> dict[str, Any]:
    """One exchange with the interviewer.

    The state moves `briefing` -> `interviewing` here rather than on the first submission:
    the interview has started when someone speaks, and a session that takes turns while
    still reporting `briefing` is a state machine describing something that is not
    happening.
    """
    if session_row.status not in OPEN_STATES:
        raise wrong_state(
            f"Session is {session_row.status!r}; turns are only taken while it is one of "
            f"{sorted(OPEN_STATES)}.",
            state=session_row.status,
        )
    item = current_item(db, session_row)
    if item is None:
        raise wrong_state(
            "Every planned item is finished; submit or end the session.",
            state=session_row.status,
        )

    if session_row.status == "briefing":
        session_row.status = "interviewing"
        db.add(session_row)
        db.commit()
        event_bus.bus().publish(
            session_row.id, "session.state", state="interviewing", reason="first turn"
        )

    result = agent_loop.run_turn(db, session_row, item, content, runner=runner, client=client)

    # `end_round` finishes the item, not the session. If it was the last one, there is
    # nothing left to interview about and the session is wrapping — grading still has to
    # happen, and `_maybe_complete` is what ends it.
    if result.ended and current_item(db, session_row) is None:
        session_row.status = "wrapping"
        db.add(session_row)
        db.commit()
        event_bus.bus().publish(
            session_row.id, "session.state", state="wrapping", reason=result.end_reason
        )

    return {
        "item_id": item.id,
        "state": session_row.status,
        "message": result.text,
        "tool_calls": result.tool_calls,
        "hints_revealed": result.hints_revealed,
        "round_ended": result.ended,
        "end_reason": result.end_reason,
        "truncated": result.truncated,
    }


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


def grade_artifact(artifact_id: str, runner: CodeRunner | None = None, client: Any = None) -> None:
    """Grade one stored submission and write what it implies.

    Runs *outside* the request (a coding grade with a complexity probe takes tens of
    seconds — docs/API.md returns 202 for exactly this reason), so it opens its own
    database session rather than borrowing a closed one.

    Never raises, and the blanket `except` below is what makes that true rather than the
    docstring saying so. An earlier version caught only the three exceptions `grade_coding`
    was expected to raise, which left everything after it — the evidence insert, the
    projection update — able to escape. The consequence was silent and permanent: the
    session's transaction rolled back, taking the `gradings` row with it, so the item
    reported `"grading"` forever, the session never completed, and a retry was refused with
    409 because the artifact already existed. The client had its 202 and never found out.
    """
    try:
        _grade(artifact_id, runner, client)
    except Exception as exc:
        LOGGER.exception("grading %s failed outside the grader", artifact_id)
        # The exception *type*, never its text. `gradings.detail` is returned verbatim by
        # `GET /sessions/{id}` and the report, and the text of a database error carries the
        # failing statement with its bound parameters — measured: a full INSERT with every
        # column and value, including the candidate's own submission. A psycopg
        # `OperationalError` would carry the host, port and role; an executor `httpx` error
        # an internal URL. The type is enough to tell a caller what class of thing went
        # wrong, and the traceback is in the log where it belongs.
        _record_crash(artifact_id, type(exc).__name__)


def _grade(artifact_id: str, runner: CodeRunner | None, client: Any = None) -> None:
    with Session(get_engine()) as db:
        artifact = db.get(Artifact, artifact_id)
        if artifact is None:  # pragma: no cover - only reachable if the row was deleted
            return
        item = corpus_item(artifact.item_id)
        if item is None:
            _record_failure(db, artifact, f"{artifact.item_id} is not in this build's corpus")
            return

        # Hints taken during the interview cost score (docs/GRADING.md), counted from the
        # turn record. Zero when the session never used the agent.
        hints = agent_loop.hints_revealed(db, artifact.session_id, artifact.item_id)
        event_bus.bus().publish(artifact.session_id, "grading.started", item_id=artifact.item_id)

        # Which grader runs is the *item's* decision, not the mode's: `grading.type` is what
        # the corpus schema makes authoritative, and a mode is just the set of items it
        # draws from. An item whose type nothing implements is a failed grading with a
        # reason, never a zero.
        grading_type = (item.grading or {}).get("type")
        try:
            if grading_type == "tests":
                language = LANGUAGES.get(artifact.language or "python")
                if language is None:
                    _record_failure(
                        db, artifact, f"{artifact.language!r} is not a language the executor runs"
                    )
                    return
                grade: CodingGrade | RubricGrade | QuantGrade = grade_coding(
                    item,
                    artifact.content,
                    runner=runner,
                    language=language,
                    hints_revealed=hints,
                )
            elif grading_type == "answer":
                grade = grade_quant(
                    item,
                    artifact.content,
                    hints_revealed=hints,
                    session_id=artifact.session_id,
                    client=client,
                )
            elif grading_type == "rubric":
                grade = grade_rubric(
                    item,
                    artifact.content,
                    hints_revealed=hints,
                    session_id=artifact.session_id,
                    client=client,
                )
            else:
                _record_failure(
                    db, artifact, f"no grader for {item.id} (grading.type={grading_type!r})"
                )
                return
        except ExecutorUnavailableError as exc:
            # The submission is not at fault and must not be scored for it. The artifact
            # stays on disk, so re-running the grader later is all it takes.
            _record_failure(db, artifact, f"executor unavailable: {exc}")
            return
        except ProblemError as exc:
            # A model grader's provider was refused or unavailable, or the budget was
            # spent. Same reasoning as above: not the candidate's fault, so not their score.
            _record_failure(db, artifact, f"grader could not reach a model: {exc.detail}")
            return
        except (ExecutorProtocolError, ValueError) as exc:
            _record_failure(db, artifact, f"grader refused this submission: {exc}")
            return

        _record_grade(db, artifact, grade)


def _record_crash(artifact_id: str, detail: str) -> None:
    """Record a failure whose own transaction may already be poisoned.

    Opens a fresh session on purpose: an `IntegrityError` mid-write leaves the original
    transaction unusable, so writing the failure row through it would fail too and the
    grading would vanish exactly as it did before.
    """
    try:
        with Session(get_engine()) as db:
            artifact = db.get(Artifact, artifact_id)
            if artifact is None:  # pragma: no cover - only if the row was deleted
                return
            _record_failure(db, artifact, f"grading crashed: {detail}")
    except Exception:
        LOGGER.exception("could not record the failed grading for %s", artifact_id)


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
    # A failure is a result too, and the client is waiting on the same event either way.
    # Reporting only successes would leave a stream that goes quiet on the one outcome
    # somebody needs to be told about.
    event_bus.bus().publish(
        artifact.session_id,
        "grading.result",
        item_id=artifact.item_id,
        status="failed",
        score=None,
        detail={"status": "failed", "detail": detail},
        evidence_written=[],
    )
    _maybe_complete(db, artifact.session_id)


def _record_grade(
    db: Session, artifact: Artifact, grade: CodingGrade | RubricGrade | QuantGrade
) -> None:
    # Before the evidence rows exist, so their `ts` values are stamped inside the critical
    # section and a replay sees them in the order they were applied.
    lock_projection(db)
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
    # After the commit, not before: an event announcing a score that a rollback then
    # discards is worse than a late one, and a client cannot un-see it.
    event_bus.bus().publish(
        artifact.session_id,
        "grading.result",
        item_id=artifact.item_id,
        status=grade.status,
        score=grade.score,
        detail=grade.as_detail(),
        evidence_written=[row.concept_id for row in evidence],
    )
    _maybe_complete(db, artifact.session_id)


def _maybe_complete(db: Session, session_id: str) -> None:
    """A session is done when every planned item has reached a terminal grading.

    A *failed* grading is terminal too: nothing can be resubmitted for that item, so
    waiting for it would leave the session open forever. Such a session completes with
    less evidence than it has items, which is the honest outcome.
    """
    session_row = db.get(InterviewSession, session_id)
    if session_row is None or session_row.status not in COMPLETABLE_STATES:
        return
    outcomes = _item_outcomes(db, session_row)
    if all(entry["status"] in {"graded", "failed"} for entry in outcomes):
        session_row.status = "complete"
        session_row.ended_at = _now()
        db.add(session_row)
        db.commit()
        event_bus.bus().publish(
            session_id, "session.state", state="complete", reason="every item is graded"
        )


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
    turns = db.exec(select(Turn.id).where(Turn.session_id == session_row.id)).first()

    # Read off this session rather than stated as a constant. Both notes used to be
    # hardcoded, and both had been false since the day the thing they denied was built —
    # a report that says "no rubric grader exists yet" while reporting rubric scores is
    # the exact failure this project treats a stale document as.
    notes: list[str] = []
    if turns is None:
        notes.append("No interviewer agent ran: there are no turns, hints or observations.")
    judged = sorted(
        {row.grader_version for row in evidence if not row.grader_version.startswith("coding.")}
    )
    if judged:
        notes.append(
            "Some scores are a model's judgement against a rubric, not a test result "
            f"({', '.join(judged)}); their evidence carries lower confidence "
            "(docs/GRADING.md)."
        )

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
        # Stated in the payload, not just in the docs: a report that silently mixed a
        # model's judgement into a column of test results would read as more certain than
        # the numbers in it are.
        "notes": notes,
    }
