"""The parts of the planner that need no database.

The behaviour that matters — what it serves, and why — is in `test_planner_db.py`,
because ranking a concept requires knowing how you have done on it.
"""

from __future__ import annotations

from api.planner import BAND_HIGH, BAND_LOW, DOMAIN_FOR_MODE, _band_distance, eligible_items


def test_only_active_instances_of_the_requested_mode_are_eligible():
    """Archetypes are attested patterns, not gradeable problems — serving one would be
    serving a description of a question instead of a question."""
    items = eligible_items("coding")
    assert items
    assert all(item.kind == "instance" for item in items)
    assert all(item.modality == "coding" for item in items)
    assert all(item.is_active for item in items)


def test_focus_concepts_narrow_the_pool():
    ids = [item.id for item in eligible_items("coding", ("monotonic-stack",))]
    assert ids == ["i.code.0002"]


def test_a_focus_nothing_matches_leaves_nothing_eligible():
    assert eligible_items("coding", ("no-such-concept",)) == []


def test_the_mode_and_domain_vocabularies_differ_by_one_name():
    """`design` is a modality and `system_design` is a domain. Conflating them produces an
    empty plan and no error, which is the worst combination available."""
    assert DOMAIN_FOR_MODE["design"] == "system_design"
    assert {mode: DOMAIN_FOR_MODE[mode] for mode in ("coding", "quant", "behavioral")} == {
        "coding": "coding",
        "quant": "quant",
        "behavioral": "behavioral",
    }


def test_an_expectation_inside_the_band_has_no_distance():
    assert _band_distance(BAND_LOW, BAND_LOW, BAND_HIGH) == 0.0
    assert _band_distance(BAND_HIGH, BAND_LOW, BAND_HIGH) == 0.0
    assert _band_distance(0.7, BAND_LOW, BAND_HIGH) == 0.0


def test_distance_grows_on_both_sides_of_the_band():
    """Too easy is as uninformative as too hard, and the planner has to treat them the
    same way or it drifts to whichever end the arithmetic favours."""
    assert _band_distance(0.95, BAND_LOW, BAND_HIGH) > 0
    assert _band_distance(0.2, BAND_LOW, BAND_HIGH) > 0
