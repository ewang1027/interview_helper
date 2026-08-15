"""Tests for the corpus validator.

The point of these is that the validator *catches* things, not just that it passes
on good input — a validator that never fails is indistinguishable from no validator.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from corpus.loader import CorpusPaths, load_concepts
from corpus.validate import (
    _registrable_domain,
    check_concept_graph,
    check_items,
    check_schema,
    run,
)

REPO_CORPUS = CorpusPaths.default()


def _errors(findings: list[Any]) -> list[str]:
    return [f.message for f in findings if f.level == "error"]


# --- the real corpus ------------------------------------------------------------


def test_real_corpus_is_valid() -> None:
    findings = run(REPO_CORPUS)
    assert _errors(findings) == []


def test_concepts_load_as_models() -> None:
    concepts = load_concepts(REPO_CORPUS)
    assert len(concepts) > 50
    assert all(c.description for c in concepts)
    ids = [c.id for c in concepts]
    assert len(ids) == len(set(ids))


def test_every_domain_is_represented() -> None:
    domains = {c.domain for c in load_concepts(REPO_CORPUS)}
    assert domains == {"coding", "quant", "system_design", "behavioral"}


def test_schema_accepts_the_real_concepts() -> None:
    schema = json.loads((REPO_CORPUS.schema / "concept.schema.json").read_text())
    raw = json.loads(REPO_CORPUS.concepts_file.read_text())["concepts"]
    assert check_schema(raw, schema, "concept") == []


# --- the validator actually catches things --------------------------------------


def test_detects_cycle() -> None:
    concepts = [
        {"id": "a", "domain": "coding", "name": "A", "description": "x" * 30, "prereqs": ["b"]},
        {"id": "b", "domain": "coding", "name": "B", "description": "x" * 30, "prereqs": ["a"]},
    ]
    assert any("cycle" in m for m in _errors(check_concept_graph(concepts)))


def test_detects_dangling_prereq() -> None:
    concepts = [
        {"id": "a", "domain": "coding", "name": "A", "description": "x" * 30, "prereqs": ["ghost"]},
    ]
    assert any("does not exist" in m for m in _errors(check_concept_graph(concepts)))


def test_detects_duplicate_concept_id() -> None:
    c = {"id": "a", "domain": "coding", "name": "A", "description": "x" * 30, "prereqs": []}
    assert any("duplicate" in m for m in _errors(check_concept_graph([c, dict(c)])))


def _item(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "i.code.0001",
        "kind": "instance",
        "domain": "coding",
        "modality": "coding",
        "archetype_id": "a.code.0001",
        "title": "A test item",
        "statement_md": "Write a function that returns the number of distinct values in a list.",
        "concepts": ["hash-set-dedup"],
        "primary_concept": "hash-set-dedup",
        "difficulty": {"band": "easy", "elo": 1200},
        "sources": [
            {
                "url": "https://one.example.com/a",
                "retrieved_at": "2026-08-01",
                "evidence": "e" * 30,
            },
            {
                "url": "https://two.example.org/b",
                "retrieved_at": "2026-08-01",
                "evidence": "f" * 30,
            },
        ],
        "corpus_version": 1,
        "grading": {
            "type": "tests",
            "languages": ["python"],
            "tests": [
                {"input": [1], "expected": 1},
                {"input": [], "expected": 0},
                {"input": [1, 1], "expected": 1},
            ],
            "reference_solutions": {"python": "def f(x): return len(set(x))"},
        },
    }
    base.update(overrides)
    return base


_ARCHETYPE = {"id": "a.code.0001", "kind": "archetype"}
_CONCEPTS = [
    {
        "id": "hash-set-dedup",
        "domain": "coding",
        "name": "Hash set membership",
        "description": "d" * 30,
        "prereqs": [],
    }
]


def test_detects_unknown_concept_reference() -> None:
    item = _item(concepts=["not-a-concept"], primary_concept="not-a-concept")
    errs = _errors(check_items([item, _ARCHETYPE], _CONCEPTS))
    assert any("unknown concept" in m for m in errs)


def test_detects_primary_concept_not_in_concepts() -> None:
    item = _item(primary_concept="hash-map-counting")
    errs = _errors(check_items([item, _ARCHETYPE], _CONCEPTS))
    assert any("not listed in concepts" in m for m in errs)


def test_detects_missing_archetype() -> None:
    item = _item(archetype_id="a.code.9999")
    errs = _errors(check_items([item, _ARCHETYPE], _CONCEPTS))
    assert any("does not exist" in m for m in errs)


def test_detects_non_independent_sources() -> None:
    same_site = [
        {"url": "https://one.example.com/a", "retrieved_at": "2026-08-01", "evidence": "e" * 30},
        {"url": "https://one.example.com/b", "retrieved_at": "2026-08-01", "evidence": "f" * 30},
    ]
    errs = _errors(check_items([_item(sources=same_site), _ARCHETYPE], _CONCEPTS))
    assert any("independent sources" in m for m in errs)


def test_detects_copied_statement() -> None:
    """The rule that keeps us from reproducing proprietary problem text."""
    lifted = (
        "given an array of integers return the indices of the two numbers such "
        "that they add up to a specific target value provided by the caller"
    )
    item = _item(
        statement_md=lifted,
        sources=[
            {"url": "https://one.example.com/a", "retrieved_at": "2026-08-01", "evidence": lifted},
            {
                "url": "https://two.example.org/b",
                "retrieved_at": "2026-08-01",
                "evidence": "f" * 30,
            },
        ],
    )
    errs = _errors(check_items([item, _ARCHETYPE], _CONCEPTS))
    assert any("original prose" in m or "overlaps" in m for m in errs)


def test_detects_missing_reference_solution() -> None:
    grading = {
        "type": "tests",
        "languages": ["python", "cpp"],
        "tests": [{"input": [1], "expected": 1}] * 3,
        "reference_solutions": {"python": "def f(x): return len(set(x))"},
    }
    errs = _errors(check_items([_item(grading=grading), _ARCHETYPE], _CONCEPTS))
    assert any("reference solution" in m for m in errs)


def test_detects_wrong_grading_type_for_modality() -> None:
    item = _item(
        grading={
            "type": "rubric",
            "criteria": [{"id": "a", "description": "x" * 20, "weight": 1.0}],
        }
    )
    errs = _errors(check_items([item, _ARCHETYPE], _CONCEPTS))
    assert any("requires grading.type" in m for m in errs)


def test_detects_rubric_weights_not_summing_to_one() -> None:
    item = _item(
        modality="design",
        domain="system_design",
        grading={
            "type": "rubric",
            "criteria": [
                {"id": "a", "description": "x" * 20, "weight": 0.3},
                {"id": "b", "description": "y" * 20, "weight": 0.3},
                {"id": "c", "description": "z" * 20, "weight": 0.3},
            ],
        },
    )
    errs = _errors(check_items([item, _ARCHETYPE], _CONCEPTS))
    assert any("weights sum" in m for m in errs)


# --- helpers ---------------------------------------------------------------------


def test_registrable_domain() -> None:
    assert _registrable_domain("https://www.example.com/x") == "example.com"
    assert _registrable_domain("http://example.org") == "example.org"
    # Two-part public suffixes keep three labels, so co.uk sites stay distinguishable.
    assert _registrable_domain("https://blog.example.co.uk/x") == "example.co.uk"
    # Subdomains of one site must collapse together, or "independent sources" is a lie.
    assert _registrable_domain("https://a.example.com/x") == _registrable_domain(
        "https://b.example.com/y"
    )


def test_items_dir_absent_is_not_an_error(tmp_path: Path) -> None:
    """Phase 0 ships concepts but no items yet; that must still validate."""
    paths = CorpusPaths(root=tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "schema").mkdir()
    (tmp_path / "data" / "concepts.json").write_text(json.dumps({"concepts": _CONCEPTS}))
    for name in ("concept.schema.json", "item.schema.json"):
        (tmp_path / "schema" / name).write_text((REPO_CORPUS.schema / name).read_text())
    assert _errors(run(paths)) == []
