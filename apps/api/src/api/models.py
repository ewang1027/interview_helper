"""The Postgres schema. See docs/ARCHITECTURE.md's Data model section (source of
truth for table purposes) and docs/PRACTICE_LOG.md (practice_problems, practice_solves,
and the concept_evidence extension).

Two id conventions coexist deliberately: corpus-sourced tables (`Concept`, `Item`) keep
the string ids already assigned by `packages/corpus` (e.g. `sliding-window`,
`i.code.0001`), since those ids are what `concept_evidence` and the corpus JSON already
key on. Everything originated at runtime (sessions, turns, practice problems, ...) gets
a fresh ULID via `api.ids.new_id`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from api.ids import new_id


def _utcnow() -> datetime:
    from datetime import UTC

    return datetime.now(UTC)


# --- Identity ----------------------------------------------------------------------


class User(SQLModel, table=True):
    """One row today. Kept multi-tenant-shaped per docs/SECURITY.md so it never
    needs a rewrite — the code does not enforce isolation, the schema allows it."""

    __tablename__ = "users"

    id: str = Field(default_factory=new_id, primary_key=True)
    github_id: int = Field(unique=True, index=True)
    created_at: datetime = Field(default_factory=_utcnow)


# --- Corpus (seeded from packages/corpus) -------------------------------------------


class Concept(SQLModel, table=True):
    __tablename__ = "concepts"

    id: str = Field(primary_key=True)  # corpus id, e.g. "sliding-window"
    domain: str
    name: str
    description: str
    band: str = "core"
    tags: list[str] = Field(default_factory=list, sa_column=Column(JSONB))
    deprecated_at: datetime | None = None


class ConceptEdge(SQLModel, table=True):
    """The prerequisite DAG: `prereq_id` must land before `concept_id`."""

    __tablename__ = "concept_edges"

    concept_id: str = Field(foreign_key="concepts.id", primary_key=True)
    prereq_id: str = Field(foreign_key="concepts.id", primary_key=True)


class Item(SQLModel, table=True):
    """Seeded from the corpus; `elo` is the *live* rating and drifts from the
    seed value in `difficulty_elo` as real outcomes come in."""

    __tablename__ = "items"

    id: str = Field(primary_key=True)  # corpus id, e.g. "i.code.0001"
    kind: str  # "archetype" | "instance"
    domain: str
    modality: str
    title: str
    statement_md: str
    primary_concept_id: str = Field(foreign_key="concepts.id")
    difficulty_band: str
    difficulty_elo: float  # the corpus seed value, immutable
    elo: float  # the live rating; starts equal to difficulty_elo, then drifts
    corpus_version: int
    archetype_id: str | None = None
    expected_minutes: int | None = None
    grading: dict[str, Any] | None = Field(default=None, sa_column=Column(JSONB))
    hints: list[str] = Field(default_factory=list, sa_column=Column(JSONB))
    follow_ups: list[str] = Field(default_factory=list, sa_column=Column(JSONB))
    created_at: datetime = Field(default_factory=_utcnow)
    deprecated_at: datetime | None = None


class ItemConcept(SQLModel, table=True):
    """Join table for an item's full `concepts` tuple (primary_concept_id above
    already covers the distinguished one; this covers the rest, including it)."""

    __tablename__ = "item_concepts"

    item_id: str = Field(foreign_key="items.id", primary_key=True)
    concept_id: str = Field(foreign_key="concepts.id", primary_key=True)


class ResearchRun(SQLModel, table=True):
    __tablename__ = "research_runs"

    id: str = Field(default_factory=new_id, primary_key=True)
    started_at: datetime
    finished_at: datetime | None = None
    searched: dict[str, Any] | None = Field(default=None, sa_column=Column(JSONB))
    added: dict[str, Any] | None = Field(default=None, sa_column=Column(JSONB))
    deprecated: dict[str, Any] | None = Field(default=None, sa_column=Column(JSONB))


# --- Sessions ------------------------------------------------------------------------


class InterviewSession(SQLModel, table=True):
    """Named to avoid shadowing `sqlmodel.Session`; the table is `sessions`."""

    __tablename__ = "sessions"

    id: str = Field(default_factory=new_id, primary_key=True)
    user_id: str = Field(foreign_key="users.id")
    mode: str  # "coding" | "quant" | "design" | "behavioral"
    budget_minutes: int
    status: str = "planning"
    plan: dict[str, Any] | None = Field(default=None, sa_column=Column(JSONB))
    started_at: datetime = Field(default_factory=_utcnow)
    ended_at: datetime | None = None


class Turn(SQLModel, table=True):
    __tablename__ = "turns"

    id: str = Field(default_factory=new_id, primary_key=True)
    session_id: str = Field(foreign_key="sessions.id", index=True)
    seq: int
    role: str  # "interviewer" | "candidate" | "tool"
    content: str
    tool_calls: dict[str, Any] | None = Field(default=None, sa_column=Column(JSONB))
    created_at: datetime = Field(default_factory=_utcnow)


class Artifact(SQLModel, table=True):
    __tablename__ = "artifacts"

    id: str = Field(default_factory=new_id, primary_key=True)
    session_id: str = Field(foreign_key="sessions.id", index=True)
    item_id: str = Field(foreign_key="items.id")
    kind: str  # "code" | "answer" | "design" | "narrative"
    language: str | None = None
    content: str
    elapsed_seconds: int
    created_at: datetime = Field(default_factory=_utcnow)


class Grading(SQLModel, table=True):
    __tablename__ = "gradings"

    id: str = Field(default_factory=new_id, primary_key=True)
    artifact_id: str = Field(foreign_key="artifacts.id", index=True)
    score: float
    detail: dict[str, Any] | None = Field(default=None, sa_column=Column(JSONB))
    grader_version: str
    created_at: datetime = Field(default_factory=_utcnow)


# --- Adaptive engine -------------------------------------------------------------------


class ConceptEvidence(SQLModel, table=True):
    """Immutable — append-only, never updated or deleted. `mastery` is a
    recomputable projection over these rows. See docs/ADAPTIVE.md.

    Two producers, distinguished by `source`: session grading (`item_id` +
    `session_id` set, `practice_problem_id` null) and the practice log
    (`practice_problem_id` set, `item_id`/`session_id` null) — see
    docs/PRACTICE_LOG.md."""

    __tablename__ = "concept_evidence"
    __table_args__ = (
        CheckConstraint(
            "(item_id IS NOT NULL) != (practice_problem_id IS NOT NULL)",
            name="concept_evidence_exactly_one_source",
        ),
    )

    id: str = Field(default_factory=new_id, primary_key=True)
    concept_id: str = Field(foreign_key="concepts.id", index=True)
    source: str  # "session_grading" | "practice_log"
    item_id: str | None = Field(default=None, foreign_key="items.id")
    session_id: str | None = Field(default=None, foreign_key="sessions.id")
    practice_problem_id: str | None = Field(default=None, foreign_key="practice_problems.id")
    score: float
    confidence: float
    ts: datetime = Field(default_factory=_utcnow)
    grader_version: str


class Mastery(SQLModel, table=True):
    """Derived projection, rebuildable from `concept_evidence` alone. Never
    hand-edited — recompute via `POST /mastery/recompute` (docs/API.md)."""

    __tablename__ = "mastery"

    user_id: str = Field(foreign_key="users.id", primary_key=True)
    concept_id: str = Field(foreign_key="concepts.id", primary_key=True)
    ability: float = 1200.0
    stability: float | None = None
    due_at: datetime | None = None
    last_seen: datetime | None = None


# --- Cost governance -------------------------------------------------------------------


class LlmCall(SQLModel, table=True):
    __tablename__ = "llm_calls"

    id: str = Field(default_factory=new_id, primary_key=True)
    session_id: str | None = Field(default=None, foreign_key="sessions.id")
    job: str  # e.g. "session_planning", "grading", "practice_log_classify"
    model: str
    provider: str  # "bedrock" | "anthropic"
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float
    latency_ms: int
    created_at: datetime = Field(default_factory=_utcnow)


# --- Practice log (docs/PRACTICE_LOG.md, Phase 9) ---------------------------------------


class PracticeProblem(SQLModel, table=True):
    __tablename__ = "practice_problems"

    id: str = Field(default_factory=new_id, primary_key=True)
    title: str
    url: str
    source_site: str  # "leetcode" | "codeforces" | "other"
    notes: str | None = None
    difficulty_label: str | None = None
    primary_concept_id: str | None = Field(default=None, foreign_key="concepts.id")
    secondary_concept_ids: list[str] = Field(default_factory=list, sa_column=Column(JSONB))
    classification_confidence: float | None = None
    classification_model: str | None = None
    status: str = "pending_classification"
    solve_count: int = 1
    stability_days: float | None = None
    due_at: datetime | None = None
    graduated_at: datetime | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class PracticeSolve(SQLModel, table=True):
    """Append-only, mirroring `concept_evidence`'s immutability."""

    __tablename__ = "practice_solves"

    id: str = Field(default_factory=new_id, primary_key=True)
    problem_id: str = Field(foreign_key="practice_problems.id", index=True)
    review_number: int  # 0 = initial solve, 1-3 = scheduled re-solves
    is_success: bool
    attempted_at: datetime = Field(default_factory=_utcnow)
    notes: str | None = None
    concept_evidence_id: str | None = Field(default=None, foreign_key="concept_evidence.id")
    created_at: datetime = Field(default_factory=_utcnow)
