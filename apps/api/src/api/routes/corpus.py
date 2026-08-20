"""Corpus routes. Moved from the root to `/api/v1` with the router (docs/API.md)."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from fastapi import APIRouter

from corpus.loader import load_concepts, load_items

router = APIRouter(tags=["corpus"])


@lru_cache
def _corpus_status() -> dict[str, Any]:
    """Cached: the corpus is a build-time artifact (docs/CORPUS.md) and does not change
    within a running process, so reloading it from disk per request was pure waste."""
    concepts = load_concepts()
    items = load_items()
    by_domain: dict[str, int] = {}
    for concept in concepts:
        by_domain[concept.domain] = by_domain.get(concept.domain, 0) + 1
    return {
        "concepts": len(concepts),
        "concepts_by_domain": by_domain,
        "items": len(items),
        "archetypes": sum(1 for i in items if i.kind == "archetype"),
        "instances": sum(1 for i in items if i.kind == "instance"),
    }


@router.get("/corpus/status")
def corpus_status() -> dict[str, Any]:
    """What content this build actually has. Useful before there is a UI."""
    return _corpus_status()
