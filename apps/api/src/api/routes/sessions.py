"""Session routes — create, submit, end, report.

Grading runs in a background task and the endpoint returns `202`, as docs/API.md
requires: a coding submission with a complexity probe takes tens of seconds, and holding
an HTTP request open for that is a bad way to wait. The spec delivers the result on the
SSE stream; that stream lands with the interviewer agent, so until then a client learns
the outcome by polling `GET /sessions/{id}`, whose `items[].status` moves from `grading`
to `graded` or `failed`.

The executor client arrives as a dependency rather than being constructed inline, so the
database-backed tests can drive the whole flow with a stub and no Docker, while the
end-to-end test injects nothing and exercises the real sandbox.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlmodel import Session

from api import sessions as service
from api.auth import CurrentPrincipal, Principal
from api.db import get_session
from api.executor_client import CodeRunner, ExecutorClient
from api.models import InterviewSession
from api.schemas import CreateSessionRequest, SubmissionRequest, TurnRequest

router = APIRouter(tags=["sessions"])


@lru_cache
def _client() -> ExecutorClient:
    """One client for the process. `httpx.Client` owns a connection pool and is safe to
    share across threads; constructing one per request leaked a pool per submission."""
    return ExecutorClient()


def get_runner() -> CodeRunner:
    return _client()


def get_model_client() -> Any:
    """The provider client for interviewer turns, or None to let `ModelRouter` build one.

    A dependency for the same reason `get_runner` is: a test drives the whole route with a
    scripted model and no network, and the alternative — reaching into `api.llm` and
    replacing a module attribute — patches a global that other tests share.
    """
    return None


DbSession = Annotated[Session, Depends(get_session)]
Runner = Annotated[CodeRunner, Depends(get_runner)]
ModelClient = Annotated[Any, Depends(get_model_client)]


def _owned(db: Session, session_id: str, principal: Principal) -> InterviewSession:
    """Every route that takes a session id goes through here, so scoping it to the caller
    is one decision rather than five chances to forget."""
    return service.get_session(db, session_id, user_id=principal.user_id)


@router.post("/sessions", status_code=201)
def create_session(
    body: CreateSessionRequest, db: DbSession, principal: CurrentPrincipal
) -> dict[str, Any]:
    """Create a session and plan it.

    docs/API.md shows `"state": "planning"` in the response because planning is expected
    to take a model call. The placeholder planner is deterministic and synchronous, so
    the session is already `briefing` by the time this returns — the plan is in the body
    either way, which is the property that mattered: you can see what it decided to drill
    you on before you start.
    """
    session_row = service.create_session(
        db,
        user_id=principal.user_id,
        mode=body.mode,
        budget_minutes=body.budget_minutes,
        focus_concepts=body.focus_concepts,
        difficulty_bias=body.difficulty_bias,
    )
    return {"id": session_row.id, "state": session_row.status, "plan": session_row.plan}


@router.get("/sessions")
def list_sessions(
    db: DbSession,
    principal: CurrentPrincipal,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(gt=0, le=100)] = 20,
) -> dict[str, Any]:
    rows = service.list_sessions(db, user_id=principal.user_id, cursor=cursor, limit=limit)
    return {
        "sessions": [
            {
                "id": row.id,
                "mode": row.mode,
                "state": row.status,
                "started_at": row.started_at,
                "ended_at": row.ended_at,
            }
            for row in rows
        ],
        # Cursor-based, so the next page starts *after* the last id returned. Null when
        # the page was not full, which is the only reliable "no more rows" signal.
        "next_cursor": rows[-1].id if len(rows) == limit else None,
    }


@router.get("/sessions/{session_id}")
def get_session_detail(
    session_id: str, db: DbSession, principal: CurrentPrincipal
) -> dict[str, Any]:
    return service.session_view(db, _owned(db, session_id, principal))


@router.post("/sessions/{session_id}/turns")
def create_turn(
    session_id: str,
    body: TurnRequest,
    db: DbSession,
    runner: Runner,
    model: ModelClient,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    """One exchange with the interviewer.

    Synchronous, unlike a submission: a turn is a conversation and the candidate is waiting
    for the reply. The SSE stream docs/API.md specifies would let the text arrive as it is
    generated; until it exists, this returns the finished message. What it costs is on the
    `llm_calls` ledger either way.
    """
    session_row = _owned(db, session_id, principal)
    return service.take_turn(db, session_row, body.content, runner=runner, client=model)


@router.post("/sessions/{session_id}/submissions", status_code=202)
def create_submission(
    session_id: str,
    body: SubmissionRequest,
    background: BackgroundTasks,
    db: DbSession,
    runner: Runner,
    model: ModelClient,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    session_row = _owned(db, session_id, principal)
    artifact = service.record_submission(
        db,
        session_row,
        item_id=body.item_id,
        kind=body.kind,
        content=body.content,
        language=body.language,
        elapsed_seconds=body.elapsed_seconds,
    )
    # The model client goes with the runner: a rubric-graded item needs one, and a test
    # that stubs the executor but not the model would reach a provider from a `db` test.
    background.add_task(service.grade_artifact, artifact.id, runner, model)
    return {
        "artifact_id": artifact.id,
        "item_id": artifact.item_id,
        "state": "grading",
        "poll": f"/api/v1/sessions/{session_id}",
    }


@router.post("/sessions/{session_id}/end")
def end_session(session_id: str, db: DbSession, principal: CurrentPrincipal) -> dict[str, Any]:
    session_row = service.end_session(db, _owned(db, session_id, principal))
    return {"id": session_row.id, "state": session_row.status, "ended_at": session_row.ended_at}


@router.get("/sessions/{session_id}/report")
def get_report(session_id: str, db: DbSession, principal: CurrentPrincipal) -> dict[str, Any]:
    return service.build_report(db, _owned(db, session_id, principal))
