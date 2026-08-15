"""Corpus validator — the Phase 0/1 gate.

Run with `make corpus-validate` (or `python -m corpus.validate`). Exits non-zero on
any error. Checks, in order:

1. JSON Schema conformance for concepts and items.
2. The concept graph is a DAG with no dangling prerequisites.
3. Every item's concept references resolve, and `primary_concept` is among them.
4. Every instance points at an archetype that exists.
5. Every item cites at least two *independent* sources (distinct registrable domains).
6. Originality — statements do not overlap their cited sources' text. This is the
   rule that keeps us from reproducing proprietary problem statements.
7. The grading contract matches the item's modality, and coding items ship a
   reference solution for every language they declare.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema

from corpus.loader import CorpusPaths, load_raw_concepts, load_raw_items

# Two shingle thresholds. A single long verbatim run is damning on its own; a high
# proportion of shared shorter runs means the statement was paraphrased too closely.
LONG_SHINGLE = 12
SHORT_SHINGLE = 8
MAX_SHORT_CONTAINMENT = 0.15

# DFS colours for cycle detection.
_WHITE, _GREY, _BLACK = 0, 1, 2

MODALITY_GRADING: dict[str, str] = {
    "coding": "tests",
    "quant": "answer",
    "design": "rubric",
    "behavioral": "rubric",
}


@dataclass(frozen=True)
class Finding:
    level: str  # "error" | "warn"
    where: str
    message: str

    def __str__(self) -> str:
        mark = "ERROR" if self.level == "error" else " WARN"
        return f"{mark}  {self.where}: {self.message}"


def _shingles(text: str, n: int) -> set[str]:
    words = text.lower().split()
    if len(words) < n:
        return set()
    return {" ".join(words[i : i + n]) for i in range(len(words) - n + 1)}


def _registrable_domain(url: str) -> str:
    """Approximate eTLD+1 — good enough to tell independent sources apart.

    Deliberately not using a public-suffix library: this is a heuristic guard for a
    single-maintainer corpus, and a wrong answer produces a warning, not a silent pass.
    """
    host = url.split("//", 1)[-1].split("/", 1)[0].split("@")[-1].split(":")[0].lower()
    parts = [p for p in host.split(".") if p]
    if len(parts) <= 2:
        return ".".join(parts)
    # Handle the common two-part suffixes (co.uk, com.au, ...) without a full PSL.
    if len(parts[-2]) <= 3 and len(parts[-1]) <= 3:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _load_schema(paths: CorpusPaths, name: str) -> dict[str, Any]:
    with (paths.schema / name).open(encoding="utf-8") as fh:
        schema: dict[str, Any] = json.load(fh)
    return schema


def check_schema(
    records: list[dict[str, Any]], schema: dict[str, Any], label: str
) -> list[Finding]:
    findings: list[Finding] = []
    validator = jsonschema.Draft202012Validator(schema)
    for rec in records:
        rid = rec.get("id", "<no id>")
        for err in sorted(validator.iter_errors(rec), key=lambda e: list(e.path)):
            loc = "/".join(str(p) for p in err.path) or "<root>"
            findings.append(Finding("error", f"{label} {rid}", f"{loc}: {err.message}"))
    return findings


def check_concept_graph(concepts: list[dict[str, Any]]) -> list[Finding]:
    findings: list[Finding] = []
    by_id: dict[str, dict[str, Any]] = {}
    for c in concepts:
        cid = c["id"]
        if cid in by_id:
            findings.append(Finding("error", f"concept {cid}", "duplicate concept id"))
        by_id[cid] = c

    for cid, c in by_id.items():
        for pre in c.get("prereqs", []):
            if pre not in by_id:
                findings.append(
                    Finding("error", f"concept {cid}", f"prereq '{pre}' does not exist")
                )
            elif pre == cid:
                findings.append(Finding("error", f"concept {cid}", "concept is its own prereq"))

    # Cycle detection via iterative DFS with colouring.
    colour: dict[str, int] = dict.fromkeys(by_id, _WHITE)

    def walk(start: str) -> None:
        stack: list[tuple[str, bool]] = [(start, False)]
        path: list[str] = []
        while stack:
            node, leaving = stack.pop()
            if leaving:
                colour[node] = _BLACK
                path.pop()
                continue
            if colour[node] == _BLACK:
                continue
            if colour[node] == _GREY:
                cycle = " -> ".join([*path[path.index(node) :], node])
                findings.append(Finding("error", "concept graph", f"cycle: {cycle}"))
                continue
            colour[node] = _GREY
            path.append(node)
            stack.append((node, True))
            for pre in by_id[node].get("prereqs", []):
                if pre in by_id and colour[pre] != _BLACK:
                    stack.append((pre, False))

    for cid in by_id:
        if colour[cid] == _WHITE:
            walk(cid)

    return findings


def check_items(items: list[dict[str, Any]], concepts: list[dict[str, Any]]) -> list[Finding]:
    findings: list[Finding] = []
    concept_ids = {c["id"] for c in concepts}
    active_concepts = {c["id"] for c in concepts if not c.get("deprecated_at")}
    item_ids: set[str] = set()
    archetype_ids = {i["id"] for i in items if i.get("kind") == "archetype"}

    for item in items:
        iid = item.get("id", "<no id>")
        where = f"item {iid}"
        if iid in item_ids:
            findings.append(Finding("error", where, "duplicate item id"))
        item_ids.add(iid)

        # --- concept references -------------------------------------------------
        for cid in item.get("concepts", []):
            if cid not in concept_ids:
                findings.append(Finding("error", where, f"unknown concept '{cid}'"))
            elif cid not in active_concepts:
                findings.append(Finding("warn", where, f"concept '{cid}' is deprecated"))
        primary = item.get("primary_concept")
        if primary and primary not in item.get("concepts", []):
            findings.append(
                Finding("error", where, f"primary_concept '{primary}' not listed in concepts")
            )

        # --- archetype linkage --------------------------------------------------
        kind = item.get("kind")
        arch = item.get("archetype_id")
        if kind == "instance":
            if not arch:
                findings.append(Finding("error", where, "instance has no archetype_id"))
            elif arch not in archetype_ids:
                findings.append(Finding("error", where, f"archetype '{arch}' does not exist"))
        elif kind == "archetype" and arch:
            findings.append(Finding("error", where, "archetype must not set archetype_id"))

        # --- source independence ------------------------------------------------
        sources = item.get("sources", [])
        domains = {_registrable_domain(s["url"]) for s in sources if s.get("url")}
        if len(domains) < 2:
            findings.append(
                Finding(
                    "error",
                    where,
                    f"needs >=2 independent sources; got {len(domains)} distinct domain(s)",
                )
            )

        # --- originality --------------------------------------------------------
        findings.extend(_check_originality(item, where))

        # --- grading contract ---------------------------------------------------
        findings.extend(_check_grading(item, where))

    return findings


def _check_originality(item: dict[str, Any], where: str) -> list[Finding]:
    findings: list[Finding] = []
    statement = item.get("statement_md", "")
    stmt_long = _shingles(statement, LONG_SHINGLE)
    stmt_short = _shingles(statement, SHORT_SHINGLE)

    for src in item.get("sources", []):
        evidence = src.get("evidence", "")
        shared_long = stmt_long & _shingles(evidence, LONG_SHINGLE)
        if shared_long:
            findings.append(
                Finding(
                    "error",
                    where,
                    f"statement shares a {LONG_SHINGLE}-word run with source "
                    f"{src.get('url')}: '{next(iter(shared_long))[:80]}...' — "
                    "statements must be original prose",
                )
            )
        ev_short = _shingles(evidence, SHORT_SHINGLE)
        if ev_short and stmt_short:
            containment = len(ev_short & stmt_short) / len(ev_short)
            if containment > MAX_SHORT_CONTAINMENT:
                findings.append(
                    Finding(
                        "error",
                        where,
                        f"statement overlaps {containment:.0%} of source "
                        f"{src.get('url')} text (limit {MAX_SHORT_CONTAINMENT:.0%})",
                    )
                )
    return findings


def _check_grading(item: dict[str, Any], where: str) -> list[Finding]:
    findings: list[Finding] = []
    grading = item.get("grading")
    modality = item.get("modality", "")

    if item.get("kind") == "archetype":
        return findings  # archetypes describe a pattern; only instances are graded
    if grading is None:
        findings.append(Finding("error", where, "instance has no grading contract"))
        return findings

    expected = MODALITY_GRADING.get(modality)
    actual = grading.get("type")
    if expected and actual != expected:
        findings.append(
            Finding(
                "error",
                where,
                f"modality '{modality}' requires grading.type '{expected}', got '{actual}'",
            )
        )

    if actual == "tests":
        declared = set(grading.get("languages", []))
        provided = set(grading.get("reference_solutions", {}))
        missing = declared - provided
        if missing:
            findings.append(
                Finding("error", where, f"no reference solution for language(s): {sorted(missing)}")
            )
        extra = provided - declared
        if extra:
            findings.append(
                Finding(
                    "warn", where, f"reference solution for undeclared language(s): {sorted(extra)}"
                )
            )
    elif actual == "answer":
        answer = grading.get("answer", {})
        if answer.get("exact") is None and answer.get("numeric") is None:
            findings.append(
                Finding("error", where, "answer grading needs an exact or numeric value")
            )
    elif actual == "rubric":
        total = sum(c.get("weight", 0) for c in grading.get("criteria", []))
        if abs(total - 1.0) > 1e-6:
            findings.append(Finding("error", where, f"rubric weights sum to {total}, expected 1.0"))

    return findings


def run(paths: CorpusPaths | None = None) -> list[Finding]:
    paths = paths or CorpusPaths.default()
    concepts = load_raw_concepts(paths)
    items = load_raw_items(paths)

    findings: list[Finding] = []
    findings += check_schema(concepts, _load_schema(paths, "concept.schema.json"), "concept")
    findings += check_schema(items, _load_schema(paths, "item.schema.json"), "item")
    findings += check_concept_graph(concepts)
    findings += check_items(items, concepts)
    return findings


def summarize(concepts: int, items: list[dict[str, Any]]) -> str:
    by_domain: dict[str, int] = defaultdict(int)
    for i in items:
        by_domain[i.get("domain", "?")] += 1
    archetypes = sum(1 for i in items if i.get("kind") == "archetype")
    instances = len(items) - archetypes
    detail = ", ".join(f"{d}={n}" for d, n in sorted(by_domain.items())) or "none yet"
    return (
        f"{concepts} concepts · {len(items)} items "
        f"({archetypes} archetypes, {instances} instances) · {detail}"
    )


def main(argv: list[str] | None = None) -> int:
    root = Path(argv[0]).resolve() if argv else None
    paths = CorpusPaths(root=root) if root else CorpusPaths.default()

    findings = run(paths)
    errors = [f for f in findings if f.level == "error"]
    warns = [f for f in findings if f.level == "warn"]

    for finding in findings:
        print(finding, file=sys.stderr if finding.level == "error" else sys.stdout)

    print(summarize(len(load_raw_concepts(paths)), load_raw_items(paths)))
    if errors:
        print(f"corpus INVALID — {len(errors)} error(s), {len(warns)} warning(s)")
        return 1
    print(f"corpus valid — 0 errors, {len(warns)} warning(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
