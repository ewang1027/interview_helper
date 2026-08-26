"""Request bodies for the session API, exactly as docs/API.md specifies them.

Response shapes are built by `api.sessions` and returned as JSON objects rather than
declared models: `plan`, `detail` and the report's per-item rows are open-ended by
design — a grader's detail blob is whatever that grader recorded — and freezing them into
Pydantic models here would either lie about that or duplicate every grader's schema.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Mode = Literal["coding", "quant", "design", "behavioral"]
ArtifactKind = Literal["code", "answer", "design", "narrative"]


class CreateSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Mode
    budget_minutes: int = Field(default=45, gt=0, le=240)
    # Empty means "let the planner decide" (docs/API.md).
    # Bounded: the planner serves at most one item per concept, so a list longer than the
    # taxonomy's largest domain cannot change a plan and only costs a scan. A 5,000-entry
    # tuple was accepted with a 201.
    focus_concepts: tuple[str, ...] = Field(default=(), max_length=60)
    difficulty_bias: float = Field(default=0.0, ge=-1, le=1)


class TurnRequest(BaseModel):
    """What the candidate says. Capped because it lands in a model request: an unbounded
    field is an unbounded bill, and a 400 naming the limit beats a budget refusal."""

    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=20_000)


class SubmissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str
    kind: ArtifactKind
    language: str | None = None
    # Capped for the same reason `TurnRequest.content` is, which was missed because a
    # coding submission goes to a sandbox rather than a model. The other three modalities
    # do not: a design, behavioral or quant submission is the *prompt* to `grade_rubric`
    # or `grade_quant`, and neither truncates it. Measured: a 5 MB submission was accepted,
    # stored and graded. The budget check runs before the call and cannot see the size, so
    # one oversized submission walks straight past `max_tokens_per_session`.
    content: str = Field(min_length=1, max_length=100_000)
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
    # The model's own schema caps secondaries at 4 and docs/PRACTICE_LOG.md says so; the
    # human-correction path enforced nothing. One PATCH carrying sixty duplicates wrote
    # sixty-one immutable evidence rows and moved a concept's ability nearly 200 Elo on a
    # single logged solve.
    secondary_concept_ids: tuple[str, ...] = Field(default=(), max_length=4)


class ImportLeetCodeRequest(BaseModel):
    """Slugs or URLs to import, and/or a public profile to read recent solves from.

    `slugs` is capped at `leetcode.MAX_SLUGS`: each one is a separate request to
    leetcode.com, so an unbounded list is both a slow HTTP handler and an impolite thing
    to point at somebody else's service.
    """

    model_config = ConfigDict(extra="forbid")

    slugs: tuple[str, ...] = Field(default=(), max_length=100)
    username: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def _needs_something(self) -> ImportLeetCodeRequest:
        if not self.slugs and not self.username:
            raise ValueError("give slugs, a username, or both")
        return self


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_success: bool
    notes: str | None = Field(default=None, max_length=4000)
    attempted_at: datetime | None = None


# --- Job applications (docs/JOBS.md) ---------------------------------------------------


Stage = Literal[
    "applied",
    "oa",
    "phone_screen",
    "round_1",
    "round_2",
    "final",
    "offer",
    "rejected",
    "withdrawn",
    "ghosted",
]


class ImportJobsRequest(BaseModel):
    """A pasted list of applications, as text.

    `text` is capped because it goes straight into a model request: an unbounded field is
    an unbounded bill, and a 400 naming the limit is a better answer than a budget refusal
    that mentions neither the paste nor its size. 100,000 characters is far more than any
    real list of applications and still well inside one call.
    """

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=100_000)


class CreateJobRequest(BaseModel):
    """One application, entered by hand.

    No classification call: you typed the role, so you know what it is. `subcategory` is
    optional and the row lands in review without it — the same state a low-confidence
    parse produces, so there is one queue rather than two.
    """

    model_config = ConfigDict(extra="forbid")

    company: str = Field(min_length=1, max_length=200)
    role: str = Field(min_length=1, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    url: str | None = Field(default=None, max_length=2000)
    subcategory: str | None = Field(default=None, max_length=64)
    stage: Stage = "applied"
    notes: str | None = Field(default=None, max_length=4000)
    applied_at: datetime | None = None


class StageRequest(BaseModel):
    """A move to a new stage. Appends an event; never overwrites the last one."""

    model_config = ConfigDict(extra="forbid")

    stage: Stage
    note: str | None = Field(default=None, max_length=1000)
    occurred_at: datetime | None = None


class JobClassificationRequest(BaseModel):
    """Confirming or correcting a tag. The big category is derived, never sent —
    which is what makes an inconsistent pair unrepresentable rather than merely unlikely."""

    model_config = ConfigDict(extra="forbid")

    subcategory: str = Field(min_length=1, max_length=64)
