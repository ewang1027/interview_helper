"""Verify the documents agree with each other about what exists.

`check_doc_links.py` proves a cross-reference *resolves*. This proves the claims on both
ends of it still agree. Two files can each be internally coherent and contradict each
other in the same breath, and nothing complains, because nothing compares them — every
drift this repo has fixed by hand was of that shape:

- `docs/ARCHITECTURE.md`'s status header still called mastery unbuilt after Phase 4
  landed (fixed in 5ff20f3, by reading it),
- README's documentation table indexed `PRACTICE_LOG` as a specification after its schema
  was migrated,
- and the phase table in README and the one in `docs/BUILDLOG.md` are two hand-maintained
  copies of one fact.

Each check below is one such comparison, chosen because it is *mechanical*: prose can say
anything, so the gate compares only the markers the docs are asked to carry. The
controlled vocabulary in BUILDLOG's state column (`complete` · `built` · `partial` ·
`not started`, prose after it) exists for exactly that reason — nuance belongs in the
sentence, the verdict belongs somewhere a script can read.

What this cannot check is whether a document is *true*. That is CLAUDE.md's rule and a
reader's job.

Usage: `uv run python scripts/check_docs.py` (run by `make check` and CI).
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
README = ROOT / "README.md"
BUILDLOG = DOCS / "BUILDLOG.md"

# Hyphen, en dash and em dash all appear in these headings, and which one is used is a
# typographic decision nobody should have to remember while editing a table. Spelled as
# escapes because the three are indistinguishable in a monospaced diff.
DASH = "[-\u2013\u2014]"

STATUS_LINE = re.compile(r"^> \*\*Status:\*\* *(.+)$", re.MULTILINE)
DOC_ROW = re.compile(r"^\| *\[([^\]]+)\]\((docs/[^)#]+)\) *\|([^|]*)\|([^|]*)\|([^|]*)\|", re.M)
README_PHASE = re.compile(r"^- \[([ x])\] \*\*(\d+) ", re.M)
BUILDLOG_PHASE = re.compile(rf"^\| *\*\*(\d+)(?:{DASH}(\d+))?\*\* *([^|]*)\| *([^|]*)\|", re.M)
STAND_DATE = re.compile(rf"^## Where things stand *{DASH} *(\d{{4}}-\d{{2}}-\d{{2}})", re.M)
WAVE_DATE = re.compile(r"^## (.*?(\d{4}-\d{2}-\d{2})) *$", re.M)
# "not built" is the common way a spec says it is a spec, so the negative form must not
# read as a claim of the positive one.
CLAIMS_BUILT = re.compile(r"(?<!not )built", re.I)

DONE = {"complete", "built"}
STATES = DONE | {"partial", "not started"}

# Floors for the vacuity guard. A parser that silently matches nothing reports perfect
# agreement, which is the one failure mode a consistency gate cannot afford.
FLOORS = {"docs": 10, "indexed": 10, "readme phases": 8, "buildlog phases": 5}


def status_of(text: str) -> str | None:
    """The one-line verdict a doc opens with, or None if it does not carry one."""
    match = STATUS_LINE.search(text)
    return match.group(1).strip() if match else None


def marker_of(cell: str) -> str:
    """The controlled-vocabulary word a BUILDLOG state cell begins with.

    Everything after the first dash or comma is prose for a reader, not for this."""
    plain = re.split(rf" *{DASH} |, ", cell.replace("*", "").strip(), maxsplit=1)[0]
    return plain.strip().lower()


def expand(start: str, end: str | None) -> list[int]:
    """One table row can span phases: `5` through `8` is a single row covering four."""
    return list(range(int(start), int(end or start) + 1))


def main() -> int:
    problems: list[str] = []
    readme = README.read_text(encoding="utf-8")
    buildlog = BUILDLOG.read_text(encoding="utf-8")
    doc_paths = sorted(DOCS.glob("*.md"))
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

    # 4. Two hand-maintained copies of one fact: README's build-status checklist and
    #    BUILDLOG's "Where things stand" table.
    readme_phases = {int(m.group(2)): m.group(1) == "x" for m in README_PHASE.finditer(readme)}
    buildlog_phases: dict[int, str] = {}
    for match in BUILDLOG_PHASE.finditer(buildlog):
        for phase in expand(match.group(1), match.group(2)):
            buildlog_phases[phase] = marker_of(match.group(4))
    counts["readme phases"] = len(readme_phases)
    counts["buildlog phases"] = len(buildlog_phases)

    for phase in sorted(set(readme_phases) - set(buildlog_phases)):
        problems.append(f"phase {phase}: in README's build status, missing from BUILDLOG's table")
    for phase in sorted(set(buildlog_phases) - set(readme_phases)):
        problems.append(f"phase {phase}: in BUILDLOG's table, missing from README's build status")

    for phase, marker in sorted(buildlog_phases.items()):
        if marker not in STATES:
            problems.append(
                f"phase {phase}: BUILDLOG state starts {marker!r}; use one of {sorted(STATES)} "
                "and put the nuance after a dash"
            )
        elif phase in readme_phases and readme_phases[phase] != (marker in DONE):
            box = "[x]" if readme_phases[phase] else "[ ]"
            problems.append(f"phase {phase}: README says {box}, BUILDLOG says {marker!r}")

    # 5. The state-of-play header must not predate the newest wave written under it.
    stand = STAND_DATE.search(buildlog)
    waves = [m.group(2) for m in WAVE_DATE.finditer(buildlog) if not m.group(1).startswith("Where")]
    if stand is None:
        problems.append("BUILDLOG: no '## Where things stand — YYYY-MM-DD' heading")
    elif waves and max(waves) > stand.group(1):
        problems.append(
            f"BUILDLOG: 'Where things stand' is dated {stand.group(1)}, "
            f"but the newest entry below it is {max(waves)}"
        )

    # 6. Guard the five above from passing vacuously — a regex that matched nothing makes
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
