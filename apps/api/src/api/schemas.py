"""Request bodies for the session API, exactly as docs/API.md specifies them.

Response shapes are built by `api.sessions` and returned as JSON objects rather than
declared models: `plan`, `detail` and the report's per-item rows are open-ended by
design — a grader's detail blob is whatever that grader recorded — and freezing them into
Pydantic models here would either lie about that or duplicate every grader's schema.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Mode = Literal["coding", "quant", "design", "behavioral"]
ArtifactKind = Literal["code", "answer", "design", "narrative"]


class CreateSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Mode
    budget_minutes: int = Field(default=45, gt=0, le=240)
    # Empty means "let the planner decide" (docs/API.md).
    focus_concepts: tuple[str, ...] = ()
    difficulty_bias: float = Field(default=0.0, ge=-1, le=1)


class TurnRequest(BaseModel):
    """What the candidate says. Capped because it lands in a model request: an unbounded
    field is an unbounded bill, and a 400 naming the limit beats a budget refusal."""

    content: str = Field(min_length=1, max_length=20_000)


class SubmissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str
    kind: ArtifactKind
    language: str | None = None
    content: str = Field(min_length=1)
    elapsed_seconds: int = Field(default=0, ge=0)
