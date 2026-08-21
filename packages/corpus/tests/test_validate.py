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
    item = _item(sources=same_site)
    findings = [f for f in check_items([item, _ARCHETYPE], _CONCEPTS) if item["id"] in f.where]
    assert any(f.level == "error" and "independent sources" in f.message for f in findings)


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


def test_detects_domain_modality_mismatch() -> None:
    """A mismatch would route an item to a grader that cannot grade it."""
    item = _item(domain="quant")  # modality stays "coding"
    errs = _errors(check_items([item, _ARCHETYPE], _CONCEPTS))
    assert any("requires modality" in m for m in errs)


def test_warns_on_cross_domain_concept_tag() -> None:
    """Legitimate occasionally, but a mis-tag writes evidence to the wrong concept."""
    concepts = [
        *_CONCEPTS,
        {
            "id": "kelly-criterion",
            "domain": "quant",
            "name": "Kelly",
            "description": "d" * 30,
            "prereqs": [],
        },
    ]
    item = _item(concepts=["hash-set-dedup", "kelly-criterion"])
    findings = [f for f in check_items([item, _ARCHETYPE], concepts) if item["id"] in f.where]
    # A cross-domain tag is a warning, never an error — the item itself is still valid.
    assert [f.message for f in findings if f.level == "error"] == []
    assert any(f.level == "warn" and "is in domain 'quant'" in f.message for f in findings)


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


def _answer_item(**rubric_overrides: Any) -> dict[str, Any]:
    """A quant instance whose reasoning_rubric can be perturbed per test."""
    criteria = rubric_overrides.pop(
        "criteria",
        [
            {"id": "a", "description": "x" * 20, "weight": 0.5, "levels": {"1": "ok"}},
            {"id": "b", "description": "y" * 20, "weight": 0.5, "levels": {"1": "ok"}},
        ],
    )
    return _item(
        modality="quant",
        domain="quant",
        concepts=["hash-set-dedup"],
        primary_concept="hash-set-dedup",
        grading={
            "type": "answer",
            "answer": {"exact": "1/3"},
            "reasoning_rubric": criteria,
        },
    )


def test_detects_reasoning_rubric_weights_not_summing_to_one() -> None:
    """The weight check used to live only in the `rubric` branch, so a quant item's
    reasoning weights were never summed. A short sum silently scales every score
    derived from those criteria."""
    item = _answer_item(
        criteria=[
            {"id": "a", "description": "x" * 20, "weight": 0.5, "levels": {"1": "ok"}},
            {"id": "b", "description": "y" * 20, "weight": 0.3, "levels": {"1": "ok"}},
        ]
    )
    errs = _errors(check_items([item, _ARCHETYPE], _CONCEPTS))
    assert any("reasoning_rubric weights sum" in m for m in errs), errs


def test_accepts_reasoning_rubric_summing_to_one() -> None:
    """Guards the opposite failure: a check that fires on everything is no check."""
    errs = _errors(check_items([_answer_item(), _ARCHETYPE], _CONCEPTS))
    assert not any("weights sum" in m for m in errs), errs


def test_detects_criterion_naming_an_unknown_concept() -> None:
    """A criterion's `concept` is what its evidence is keyed on, and
    `concept_evidence.concept_id` is a foreign key — an unresolvable one is an insert
    failure at grading time, not a mis-tag."""
    item = _answer_item(
        criteria=[
            {
                "id": "a",
                "description": "x" * 20,
                "weight": 1.0,
                "levels": {"1": "ok"},
                "concept": "not-a-real-concept",
            }
        ]
    )
    errs = _errors(check_items([item, _ARCHETYPE], _CONCEPTS))
    assert any("unknown concept 'not-a-real-concept'" in m for m in errs), errs


def _rubric_item(criteria: list[dict[str, Any]]) -> dict[str, Any]:
    return _item(
        modality="design", domain="system_design", grading={"type": "rubric", "criteria": criteria}
    )


def _warnings(findings: list[Any]) -> list[str]:
    return [f.message for f in findings if f.level == "warn"]


def test_warns_when_no_rubric_criterion_measures_the_primary_concept() -> None:
    """An item's rating moves on the attempt's first evidence row naming its primary
    concept, so a rubric that names it nowhere leaves that rating at the author's prior
    forever — and a rating that never moves looks exactly like a well-calibrated one.
    `i.design.0003` is the live instance."""
    item = _rubric_item(
        [
            {"id": "a", "description": "x" * 20, "weight": 0.5, "levels": {"1": "ok"}},
            {"id": "b", "description": "y" * 20, "weight": 0.5, "levels": {"1": "ok"}},
        ]
    )
    warns = _warnings(check_items([item, _ARCHETYPE], _CONCEPTS))
    assert any("never move from its seed" in m for m in warns), warns


def test_does_not_warn_when_a_criterion_measures_the_primary_concept() -> None:
    """Guards the opposite failure: a check that fires on everything is no check."""
    item = _rubric_item(
        [
            {
                "id": "a",
                "description": "x" * 20,
                "weight": 1.0,
                "levels": {"1": "ok"},
                "concept": "hash-set-dedup",
            }
        ]
    )
    warns = _warnings(check_items([item, _ARCHETYPE], _CONCEPTS))
    assert not any("never move from its seed" in m for m in warns), warns


def test_detects_duplicate_criterion_id() -> None:
    item = _answer_item(
        criteria=[
            {"id": "same", "description": "x" * 20, "weight": 0.5, "levels": {"1": "ok"}},
            {"id": "same", "description": "y" * 20, "weight": 0.5, "levels": {"1": "ok"}},
        ]
    )
    errs = _errors(check_items([item, _ARCHETYPE], _CONCEPTS))
    assert any("duplicate criterion id" in m for m in errs), errs


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


def test_short_domains_are_not_mistaken_for_public_suffixes() -> None:
    """Firm sites are exactly where three-letter domains live.

    Inferring a two-part suffix from label length treats `imc.com` as the suffix and
    keeps the subdomain, so one firm's site splits into several registrable domains.
    """
    assert _registrable_domain("https://blog.imc.com/x") == "imc.com"
    assert _registrable_domain("https://www.imc.com/y") == "imc.com"
    assert _registrable_domain("https://careers.drw.com/x") == _registrable_domain(
        "https://www.drw.com/y"
    )


def test_hosting_suffixes_keep_the_publisher_apart() -> None:
    """Two github.io pages are two authors, not one site echoing itself."""
    assert _registrable_domain("https://alice.github.io/post") == "alice.github.io"
    assert _registrable_domain("https://alice.github.io/p") != _registrable_domain(
        "https://bob.github.io/p"
    )


def test_two_subdomains_of_a_short_domain_fail_the_independence_check() -> None:
    """The consequence the split caused, asserted where it actually bites.

    Findings are filtered to this item: the bare archetype fixture carries no sources
    of its own, so an unfiltered search for the message would pass whatever the item
    does.
    """
    one_firm = [
        {"url": "https://blog.imc.com/a", "retrieved_at": "2026-08-01", "evidence": "e" * 30},
        {"url": "https://www.imc.com/b", "retrieved_at": "2026-08-01", "evidence": "f" * 30},
    ]
    item = _item(sources=one_firm)
    findings = [f for f in check_items([item, _ARCHETYPE], _CONCEPTS) if item["id"] in f.where]
    assert any(f.level == "error" and "independent sources" in f.message for f in findings)


def test_items_dir_absent_is_not_an_error(tmp_path: Path) -> None:
    """Phase 0 ships concepts but no items yet; that must still validate."""
    paths = CorpusPaths(root=tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "schema").mkdir()
    (tmp_path / "data" / "concepts.json").write_text(json.dumps({"concepts": _CONCEPTS}))
    for name in ("concept.schema.json", "item.schema.json"):
        (tmp_path / "schema" / name).write_text((REPO_CORPUS.schema / name).read_text())
    assert _errors(run(paths)) == []
