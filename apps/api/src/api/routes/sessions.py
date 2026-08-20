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

from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlmodel import Session

from api import sessions as service
from api.db import get_session
from api.executor_client import CodeRunner, ExecutorClient
from api.schemas import CreateSessionRequest, SubmissionRequest

router = APIRouter(tags=["sessions"])


def get_runner() -> CodeRunner:
    return ExecutorClient()


DbSession = Annotated[Session, Depends(get_session)]
Runner = Annotated[CodeRunner, Depends(get_runner)]


@router.post("/sessions", status_code=201)
def create_session(body: CreateSessionRequest, db: DbSession) -> dict[str, Any]:
    """Create a session and plan it.

    docs/API.md shows `"state": "planning"` in the response because planning is expected
    to take a model call. The placeholder planner is deterministic and synchronous, so
    the session is already `briefing` by the time this returns — the plan is in the body
    either way, which is the property that mattered: you can see what it decided to drill
    you on before you start.
    """
    session_row = service.create_session(
        db,
        mode=body.mode,
        budget_minutes=body.budget_minutes,
        focus_concepts=body.focus_concepts,
        difficulty_bias=body.difficulty_bias,
    )
    return {"id": session_row.id, "state": session_row.status, "plan": session_row.plan}


@router.get("/sessions")
def list_sessions(
    db: DbSession,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(gt=0, le=100)] = 20,
) -> dict[str, Any]:
    rows = service.list_sessions(db, cursor=cursor, limit=limit)
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
def get_session_detail(session_id: str, db: DbSession) -> dict[str, Any]:
    return service.session_view(db, service.get_session(db, session_id))


@router.post("/sessions/{session_id}/submissions", status_code=202)
def create_submission(
    session_id: str,
    body: SubmissionRequest,
    background: BackgroundTasks,
    db: DbSession,
    runner: Runner,
) -> dict[str, Any]:
    session_row = service.get_session(db, session_id)
    artifact = service.record_submission(
        db,
        session_row,
        item_id=body.item_id,
        kind=body.kind,
        content=body.content,
        language=body.language,
        elapsed_seconds=body.elapsed_seconds,
    )
    background.add_task(service.grade_artifact, artifact.id, runner)
    return {
        "artifact_id": artifact.id,
        "item_id": artifact.item_id,
        "state": "grading",
        "poll": f"/api/v1/sessions/{session_id}",
    }


@router.post("/sessions/{session_id}/end")
def end_session(session_id: str, db: DbSession) -> dict[str, Any]:
    session_row = service.end_session(db, service.get_session(db, session_id))
    return {"id": session_row.id, "state": session_row.status, "ended_at": session_row.ended_at}


@router.get("/sessions/{session_id}/report")
def get_report(session_id: str, db: DbSession) -> dict[str, Any]:
    return service.build_report(db, service.get_session(db, session_id))
