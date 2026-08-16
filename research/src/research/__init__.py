"""Build-time corpus research pipeline.

Runs as Claude Code sessions on a developer machine, never as a deployed service:
it reads the web, writes JSON into `packages/corpus/data/items/`, and commits. See
`docs/RESEARCH.md` for the five stages and `research/README.md` for how to run one.
"""

__all__ = ["density", "runlog", "spotcheck"]
