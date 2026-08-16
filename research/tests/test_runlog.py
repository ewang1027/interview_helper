"""Provenance checks, each proved by the failure it catches.

Phase 0's rule holds here: a check that only ever passes is indistinguishable from no
check, so every test below constructs the defect and asserts the checker sees it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from research.runlog import ResearchPaths, check_provenance, check_run_schema, load_runs

SCHEMA: dict[str, Any] = json.loads(ResearchPaths.default().schema_file.read_text(encoding="utf-8"))


def a_run(**overrides: Any) -> dict[str, Any]:
    run: dict[str, Any] = {
        "run_id": "2026-01-01-test",
        "started_at": "2026-01-01",
        "domains": ["coding"],
        "queries": [{"query": "how do interviews go", "domain": "coding", "results": 3}],
        "sources_seen": [
            {"url": "https://example.com/a", "tier": "firsthand", "used": True},
        ],
        "outcome": {
            "archetypes_added": 1,
            "archetypes_merged": 0,
            "instances_authored": 1,
        },
    }
    run.update(overrides)
    return run


def an_item(**overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": "a.code.0001",
        "sources": [{"url": "https://example.com/a"}],
    }
    item.update(overrides)
    return item


def test_valid_run_and_item_pair_is_clean() -> None:
    assert check_run_schema([a_run()], SCHEMA) == []
    assert check_provenance([an_item()], [a_run()]) == []


def test_schema_catches_bad_run_id() -> None:
    findings = check_run_schema([a_run(run_id="phase1")], SCHEMA)
    assert any("run_id" in f.message for f in findings)


def test_schema_catches_unknown_field() -> None:
    findings = check_run_schema([a_run(cost_usd=12)], SCHEMA)
    assert findings and all(f.level == "error" for f in findings)


def test_schema_catches_duplicate_run_id() -> None:
    findings = check_run_schema([a_run(), a_run()], SCHEMA)
    assert any("duplicate run_id" in f.message for f in findings)


def test_provenance_catches_source_no_run_ever_saw() -> None:
    item = an_item(sources=[{"url": "https://nowhere.example/x"}])
    findings = check_provenance([item], [a_run()])
    assert any("no research run records" in f.message for f in findings)


def test_provenance_catches_run_claiming_an_unused_source_as_used() -> None:
    findings = check_provenance([], [a_run()])
    assert any("marked used but no item cites it" in f.message for f in findings)


def test_provenance_catches_cited_source_marked_unused() -> None:
    run = a_run(sources_seen=[{"url": "https://example.com/a", "tier": "listicle", "used": False}])
    findings = check_provenance([an_item()], [run])
    assert any("marked unused" in f.message for f in findings)


def test_load_runs_tolerates_a_missing_directory(tmp_path: Path) -> None:
    assert load_runs(ResearchPaths(root=tmp_path)) == []
