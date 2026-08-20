"""Verify every internal doc link resolves — file *and* heading anchor.

Written after an audit found four broken anchors that an existence-only check had
reported clean. Anchors rot invisibly: renaming a heading breaks every link to it, and
nothing complains, so a reader following a cross-reference lands at the top of the page
and quietly loses the thread.

The headings that broke were ones encoding a date or a migration id, which change. Prefer
a stable heading with the volatile detail in the body.

Usage: `uv run python scripts/check_doc_links.py` (run by `make check`).
"""

from __future__ import annotations

import pathlib
import re
import sys

LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
HEADING = re.compile(r"^#{1,6}\s+(.*)$")


def slugify(heading: str) -> str:
    """GitHub's heading-to-anchor rule, closely enough for internal links."""
    text = re.sub(r"`([^`]*)`", r"\1", heading)
    text = re.sub(r"\*\*?([^*]*)\*\*?", r"\1", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"\s+", "-", text).strip("-")


def anchors_in(text: str) -> set[str]:
    return {slugify(m.group(1).strip()) for line in text.splitlines() if (m := HEADING.match(line))}


def main() -> int:
    root = pathlib.Path(__file__).resolve().parents[1]
    paths = [*sorted(root.glob("docs/*.md")), root / "README.md", root / "CLAUDE.md"]
    text_of = {p: p.read_text(encoding="utf-8") for p in paths}
    anchor_of = {p: anchors_in(t) for p, t in text_of.items()}

    problems: list[str] = []
    for path, text in text_of.items():
        rel = path.relative_to(root)
        for match in LINK.finditer(text):
            target = match.group(2).strip()
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            file_part, _, fragment = target.partition("#")
            resolved = (path.parent / file_part).resolve() if file_part else path
            if not resolved.exists():
                problems.append(f"{rel}: missing file -> {target}")
                continue
            if fragment and resolved in anchor_of and fragment not in anchor_of[resolved]:
                problems.append(f"{rel}: no such heading -> {target}")

    for problem in problems:
        print(f"  {problem}")
    print(f"doc links: {len(problems)} broken across {len(paths)} file(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
