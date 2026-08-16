"""FastAPI entrypoint.

Phase 3: DB engine, ModelRouter and the schema exist; the session/grading/mastery
routes from docs/API.md do not land here yet — this is the infra slice only.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from fastapi import FastAPI

from api import __version__
from corpus.loader import load_concepts, load_items

app = FastAPI(
    title="interview_helper API",
    version=__version__,
    description="Adaptive mock-interview trainer for SWE and quant-trading loops.",
)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness. Deliberately does no I/O so it cannot fail for a downstream reason."""
    return {"status": "ok", "version": __version__}


@lru_cache
def _corpus_status() -> dict[str, Any]:
    """Cached: the corpus is a build-time artifact (docs/CORPUS.md) and does not
    change within a running process, so reloading it from disk per request — the
    Phase 0 behaviour — was pure waste. Was flagged in docs/BUILDLOG.md as a known
    Phase 3 fix."""
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


@app.get("/corpus/status")
def corpus_status() -> dict[str, Any]:
    """What content this build actually has. Useful before there is a UI."""
    return _corpus_status()
