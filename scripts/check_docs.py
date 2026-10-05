"""Verify the documents agree with each other about what exists.

`check_doc_links.py` proves a cross-reference *resolves*. This proves the claims on both
ends of it still agree. Two files can each be internally coherent and contradict each
other in the same breath, and nothing complains, because nothing compares them — every
drift this repo has fixed by hand was of that shape:

- `docs/ARCHITECTURE.md`'s status header still called mastery unbuilt after Phase 4
  landed (fixed in 5ff20f3, by reading it),
- and README's documentation table indexed `PRACTICE_LOG` as a specification after its
  schema was migrated.

Each check below is one such comparison, chosen because it is *mechanical*: prose can say
anything, so the gate compares only the markers the docs are asked to carry.

Only docs git tracks are checked. Local, untracked notes can sit in docs/ and CI never
sees them.

What this cannot check is whether a document is *true*. That is a reader's job.

Usage: `uv run python scripts/check_docs.py` (run by `make check` and CI).
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
README = ROOT / "README.md"

STATUS_LINE = re.compile(r"^> \*\*Status:\*\* *(.+)$", re.MULTILINE)
DOC_ROW = re.compile(r"^\| *\[([^\]]+)\]\((docs/[^)#]+)\) *\|([^|]*)\|([^|]*)\|([^|]*)\|", re.M)
# "not built" is the common way a spec says it is a spec, so the negative form must not
# read as a claim of the positive one.
CLAIMS_BUILT = re.compile(r"(?<!not )built", re.I)

# Floors for the vacuity guard. A parser that silently matches nothing reports perfect
# agreement, which is the one failure mode a consistency gate cannot afford.
FLOORS = {"docs": 10, "indexed": 10}


def status_of(text: str) -> str | None:
    """The one-line verdict a doc opens with, or None if it does not carry one."""
    match = STATUS_LINE.search(text)
    return match.group(1).strip() if match else None


def tracked_docs() -> list[pathlib.Path]:
    names = subprocess.run(
        ["git", "ls-files", "docs/*.md"],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return sorted(ROOT / name for name in names)


def main() -> int:
    problems: list[str] = []
    readme = README.read_text(encoding="utf-8")
    doc_paths = tracked_docs()
    counts: dict[str, int] = {"docs": len(doc_paths)}

    # 1. Every doc opens with a status, because a reader cannot calibrate prose that does
    #    not say whether it describes something that exists.
    statuses: dict[str, str] = {}
    for path in doc_paths:
        status = status_of(path.read_text(encoding="utf-8"))
        if status is None:
            problems.append(f"{path.relative_to(ROOT)}: no '> **Status:**' line in the header")
        else:
            statuses[path.name] = status

    # 2. README's documentation table indexes every doc, and only docs that exist. A doc
    #    nobody indexed is a doc nobody reads; a row pointing nowhere is a broken promise.
    rows = {m.group(2): (m.group(1), m.group(5).strip()) for m in DOC_ROW.finditer(readme)}
    indexed = {pathlib.PurePosixPath(target).name for target in rows}
    counts["indexed"] = len(indexed)
    on_disk = {path.name for path in doc_paths}
    for name in sorted(on_disk - indexed):
        problems.append(f"docs/{name}: exists but is not in README's documentation table")
    for name in sorted(indexed - on_disk):
        problems.append(f"README: documentation table indexes docs/{name}, which does not exist")

    # 3. The narrow half of "the table agrees with the doc". Comparing two pieces of prose
    #    is brittle; comparing a doc that claims to be built against a row that calls it a
    #    spec is not, and that is the drift that actually happens.
    for target, (label, cell) in sorted(rows.items()):
        status = statuses.get(pathlib.PurePosixPath(target).name)
        if status is None:
            continue
        built = bool(CLAIMS_BUILT.search(status))
        if cell.lower().startswith("spec") and built:
            problems.append(
                f"README: {label} is indexed as '{cell}', but {target} says: {status[:60]!r}"
            )
        if "✅" in cell and not built:
            problems.append(
                f"README: {label} is indexed as '{cell}', but {target} claims nothing built"
            )

    # 4. Guard the three above from passing vacuously — a regex that matched nothing makes
    #    every set difference empty and reports perfect agreement.
    for what, floor in FLOORS.items():
        if counts.get(what, 0) < floor:
            problems.append(
                f"parser found only {counts.get(what, 0)} {what} (expected >= {floor}) — "
                "the format changed and this gate is no longer reading it"
            )

    for problem in problems:
        print(f"  {problem}")
    tally = " · ".join(f"{v} {k}" for k, v in counts.items())
    print(f"doc consistency: {len(problems)} problem(s) across {tally}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
