"""FastAPI entrypoint.

Phase 0: health and corpus-status endpoints, enough for the compose stack to come up
and for readiness probes to be wired before there is anything to be ready for.
"""

from __future__ import annotations

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


@app.get("/corpus/status")
def corpus_status() -> dict[str, Any]:
    """What content this build actually has. Useful before there is a UI."""
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
