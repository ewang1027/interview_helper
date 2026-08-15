"""Locate and load the corpus from disk."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from corpus.models import Concept, Item


@dataclass(frozen=True)
class CorpusPaths:
    """Where the corpus lives. Resolved from this file so it works from any cwd."""

    root: Path

    @classmethod
    def default(cls) -> CorpusPaths:
        # src/corpus/loader.py -> src/corpus -> src -> packages/corpus
        return cls(root=Path(__file__).resolve().parents[2])

    @property
    def data(self) -> Path:
        return self.root / "data"

    @property
    def schema(self) -> Path:
        return self.root / "schema"

    @property
    def concepts_file(self) -> Path:
        return self.data / "concepts.json"

    @property
    def items_dir(self) -> Path:
        return self.data / "items"


def _read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def load_concepts(paths: CorpusPaths | None = None) -> list[Concept]:
    paths = paths or CorpusPaths.default()
    payload = _read_json(paths.concepts_file)
    return [Concept.model_validate(c) for c in payload["concepts"]]


def load_items(paths: CorpusPaths | None = None) -> list[Item]:
    """Load every item file under `data/items/`.

    Items are sharded one JSON file per domain so the research pipeline can append
    to a single domain without rewriting (or conflicting on) the whole corpus.
    """
    paths = paths or CorpusPaths.default()
    if not paths.items_dir.exists():
        return []
    items: list[Item] = []
    for path in sorted(paths.items_dir.glob("*.json")):
        payload = _read_json(path)
        items.extend(Item.model_validate(raw) for raw in payload.get("items", []))
    return items


def load_raw_concepts(paths: CorpusPaths | None = None) -> list[dict[str, Any]]:
    """Unvalidated concept dicts — used by the validator, which checks JSON Schema first."""
    paths = paths or CorpusPaths.default()
    payload: dict[str, Any] = _read_json(paths.concepts_file)
    concepts: list[dict[str, Any]] = payload["concepts"]
    return concepts


def load_raw_items(paths: CorpusPaths | None = None) -> list[dict[str, Any]]:
    """Unvalidated item dicts — used by the validator."""
    paths = paths or CorpusPaths.default()
    if not paths.items_dir.exists():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(paths.items_dir.glob("*.json")):
        payload: dict[str, Any] = _read_json(path)
        out.extend(payload.get("items", []))
    return out
