"""Typed views over the corpus JSON.

These mirror `schema/*.json`. The JSON Schema is authoritative for *validation*
(the validator checks against it directly); these models exist so the rest of the
codebase gets attribute access and mypy coverage instead of dict spelunking.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Domain = Literal["coding", "quant", "system_design", "behavioral"]
Modality = Literal["coding", "quant", "design", "behavioral"]
Band = Literal["foundational", "core", "advanced"]
DifficultyBand = Literal["warmup", "easy", "medium", "hard", "expert"]


class Concept(BaseModel):
    """A node in the concept DAG — the unit of mastery."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    domain: Domain
    name: str
    description: str
    prereqs: tuple[str, ...] = ()
    band: Band = "core"
    tags: tuple[str, ...] = ()
    deprecated_at: date | None = None


class Source(BaseModel):
    """Evidence that an archetype is really asked. Never a source of copied text."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    url: str
    title: str | None = None
    retrieved_at: date
    evidence: str


class Difficulty(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    band: DifficultyBand
    elo: float = Field(ge=600, le=2800)


class Item(BaseModel):
    """An archetype (attested pattern) or an instance (concrete gradeable problem)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    kind: Literal["archetype", "instance"]
    domain: Domain
    modality: Modality
    title: str
    statement_md: str
    concepts: tuple[str, ...]
    primary_concept: str
    difficulty: Difficulty
    sources: tuple[Source, ...]
    corpus_version: int
    archetype_id: str | None = None
    expected_minutes: int | None = None
    # Grading is a discriminated union in JSON Schema; keeping it loose here avoids
    # duplicating that contract in two places, and the validator enforces the shape.
    grading: dict[str, Any] | None = None
    hints: tuple[str, ...] = ()
    follow_ups: tuple[str, ...] = ()
    created_at: date | None = None
    deprecated_at: date | None = None

    @property
    def is_active(self) -> bool:
        return self.deprecated_at is None
