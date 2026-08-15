"""Versioned interview-question corpus: schema, loader, and validator.

The corpus is a build-time artifact. `research/` (driven by Claude Code) writes it;
this package loads and validates it; `apps/api` seeds it into Postgres. Nothing at
runtime generates corpus items, which is what makes sessions reproducible and the
graders deterministic.
"""

from corpus.loader import CorpusPaths, load_concepts, load_items
from corpus.models import Concept, Item

__all__ = ["Concept", "CorpusPaths", "Item", "load_concepts", "load_items"]
