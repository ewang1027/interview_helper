"""Spot-check sampling — reproducible, or the gate is unauditable."""

from __future__ import annotations

from typing import Any

from research.spotcheck import render, sample


def _items() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for n in range(20):
        domain = "coding" if n % 2 == 0 else "quant"
        items.append(
            {
                "id": f"i.{'code' if domain == 'coding' else 'quant'}.{n:04d}",
                "kind": "instance",
                "domain": domain,
                "title": f"Instance {n}",
                "statement_md": "A statement long enough to render.",
                "sources": [{"url": "https://one.com/a"}],
            }
        )
    items.append({"id": "a.code.0001", "kind": "archetype", "domain": "coding"})
    return items


def test_same_seed_samples_the_same_instances() -> None:
    first = sample(_items(), 5, seed=7)
    second = sample(_items(), 5, seed=7)
    assert [i["id"] for i in first] == [i["id"] for i in second]


def test_different_seeds_generally_differ() -> None:
    a = [i["id"] for i in sample(_items(), 5, seed=1)]
    b = [i["id"] for i in sample(_items(), 5, seed=2)]
    assert a != b


def test_archetypes_are_never_sampled() -> None:
    picked = sample(_items(), 21, seed=1)
    assert all(i["kind"] == "instance" for i in picked)


def test_domain_filter_narrows_the_pool() -> None:
    picked = sample(_items(), 5, seed=1, domain="quant")
    assert {i["domain"] for i in picked} == {"quant"}


def test_asking_for_more_than_exists_returns_everything() -> None:
    picked = sample(_items(), 500, seed=1)
    assert len(picked) == 20


def test_render_includes_the_statement_and_id() -> None:
    text = render(_items()[0])
    assert "i.code.0000" in text
    assert "A statement long enough to render." in text
