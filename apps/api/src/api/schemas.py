"""Request bodies for the session API, exactly as docs/API.md specifies them.

Response shapes are built by `api.sessions` and returned as JSON objects rather than
declared models: `plan`, `detail` and the report's per-item rows are open-ended by
design — a grader's detail blob is whatever that grader recorded — and freezing them into
Pydantic models here would either lie about that or duplicate every grader's schema.
"""

from __future__ import annotations

from datetime import datetime
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


# --- Practice log (docs/PRACTICE_LOG.md) ----------------------------------------------


SourceSite = Literal["leetcode", "codeforces", "other"]


class LogProblemRequest(BaseModel):
    """A problem you solved elsewhere.

    `url` is a pointer and is never fetched — docs/PRACTICE_LOG.md's manual-entry-only
    rule, which is what keeps someone else's problem text out of this repo. `notes` is
    your own writing for the same reason, and it is the field most likely to be pasted
    into, so it is capped rather than trusted.
    """

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=300)
    url: str = Field(min_length=1, max_length=2000)
    source_site: SourceSite = "other"
    notes: str | None = Field(default=None, max_length=4000)
    difficulty_label: str | None = Field(default=None, max_length=64)
    solved_at: datetime | None = None


class ClassificationRequest(BaseModel):
    """Confirming or correcting what the classifier proposed."""

    model_config = ConfigDict(extra="forbid")

    primary_concept_id: str = Field(min_length=1)
    secondary_concept_ids: tuple[str, ...] = ()


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_success: bool
    notes: str | None = Field(default=None, max_length=4000)
    attempted_at: datetime | None = None
