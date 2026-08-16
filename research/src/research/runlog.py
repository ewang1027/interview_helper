"""Research run records — the provenance half of the pipeline.

`docs/RESEARCH.md` promises that "why is this question in the corpus?" stays answerable
months later. That is only true if the sources an item cites were actually seen by a
recorded run, so this module checks both directions:

- every run record under `research/runs/` conforms to `research/schema/run.schema.json`;
- every URL cited by a corpus item appears in some run's `sources_seen`;
- every `sources_seen` entry's `used` flag matches whether an item actually cites it.

That last one is the mirror check. Asking only "is every cited source recorded?" would
miss a run record claiming credit for sources nothing uses, which is how provenance
quietly drifts from fiction to accepted fact.

Run with `make research-check`.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema

from corpus.loader import CorpusPaths, load_raw_items
from corpus.validate import Finding


@dataclass(frozen=True)
class ResearchPaths:
    """Where the research pipeline's own files live."""

    root: Path

    @classmethod
    def default(cls) -> ResearchPaths:
        # src/research/runlog.py -> src/research -> src -> research/
        return cls(root=Path(__file__).resolve().parents[2])

    @property
    def runs_dir(self) -> Path:
        return self.root / "runs"

    @property
    def schema_file(self) -> Path:
        return self.root / "schema" / "run.schema.json"


def load_runs(paths: ResearchPaths | None = None) -> list[dict[str, Any]]:
    """Every run record on disk, oldest filename first."""
    paths = paths or ResearchPaths.default()
    if not paths.runs_dir.exists():
        return []
    runs: list[dict[str, Any]] = []
    for path in sorted(paths.runs_dir.glob("*.json")):
        with path.open(encoding="utf-8") as fh:
            runs.append(json.load(fh))
    return runs


def check_run_schema(runs: list[dict[str, Any]], schema: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    validator = jsonschema.Draft202012Validator(schema)
    seen_ids: set[str] = set()
    for run in runs:
        rid = run.get("run_id", "<no run_id>")
        where = f"run {rid}"
        if rid in seen_ids:
            findings.append(Finding("error", where, "duplicate run_id"))
        seen_ids.add(rid)
        for err in sorted(validator.iter_errors(run), key=lambda e: list(e.path)):
            loc = "/".join(str(p) for p in err.path) or "<root>"
            findings.append(Finding("error", where, f"{loc}: {err.message}"))
    return findings


def check_provenance(items: list[dict[str, Any]], runs: list[dict[str, Any]]) -> list[Finding]:
    """Every cited URL was seen by a run, and every `used` flag tells the truth."""
    findings: list[Finding] = []

    seen: dict[str, list[dict[str, Any]]] = {}
    for run in runs:
        for src in run.get("sources_seen", []):
            seen.setdefault(src["url"], []).append(src)

    cited: set[str] = set()
    for item in items:
        iid = item.get("id", "<no id>")
        for src in item.get("sources", []):
            url = src.get("url", "")
            cited.add(url)
            if url not in seen:
                findings.append(
                    Finding(
                        "error",
                        f"item {iid}",
                        f"cites {url}, which no research run records having seen",
                    )
                )

    for url, entries in sorted(seen.items()):
        claimed_used = any(e.get("used") for e in entries)
        if claimed_used and url not in cited:
            findings.append(
                Finding("error", "research runs", f"{url} is marked used but no item cites it")
            )
        elif not claimed_used and url in cited:
            findings.append(
                Finding("error", "research runs", f"{url} is cited by an item but marked unused")
            )
    return findings


def run(
    paths: ResearchPaths | None = None, corpus_paths: CorpusPaths | None = None
) -> list[Finding]:
    paths = paths or ResearchPaths.default()
    runs = load_runs(paths)
    with paths.schema_file.open(encoding="utf-8") as fh:
        schema: dict[str, Any] = json.load(fh)

    findings = check_run_schema(runs, schema)
    findings += check_provenance(load_raw_items(corpus_paths), runs)
    return findings


def main(argv: list[str] | None = None) -> int:
    paths = ResearchPaths.default()
    if argv and Path(argv[0]).is_dir():
        paths = ResearchPaths(root=Path(argv[0]).resolve())

    findings = run(paths)
    for finding in findings:
        print(finding, file=sys.stderr if finding.level == "error" else sys.stdout)

    runs = load_runs(paths)
    urls = {s["url"] for r in runs for s in r.get("sources_seen", [])}
    queries = sum(len(r.get("queries", [])) for r in runs)
    print(f"{len(runs)} research run(s) · {queries} queries · {len(urls)} distinct URLs seen")

    errors = [f for f in findings if f.level == "error"]
    if errors:
        print(f"provenance INVALID — {len(errors)} error(s)")
        return 1
    print("provenance intact — every cited source traces to a recorded run")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
