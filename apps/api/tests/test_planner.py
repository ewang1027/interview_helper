"""The placeholder planner. Hermetic — it reads the corpus, not the database.

What matters about a placeholder is that it is *honest* and *deterministic*: it must not
be mistakable for the Phase 4 engine, and the same request must produce the same session
twice, or a bug found in one is unreproducible in the next.
"""

from __future__ import annotations

from api.planner import STRATEGY, build_plan, eligible_items, plan_item_ids


def test_a_plan_says_it_is_not_adaptive():
    plan = build_plan("coding", 45)
    assert plan["adaptive"] is False
    assert plan["strategy"] == STRATEGY
    assert "no mastery data" in plan["why"].lower()


def test_only_active_instances_of_the_requested_mode_are_eligible():
    """Archetypes are attested patterns, not gradeable problems — serving one would be
    serving a description of a question instead of a question."""
    items = eligible_items("coding")
    assert items
    assert all(item.kind == "instance" for item in items)
    assert all(item.modality == "coding" for item in items)
    assert all(item.is_active for item in items)


def test_the_plan_fills_the_budget_without_overrunning_it():
    small = build_plan("coding", 45)
    large = build_plan("coding", 90)

    assert small["estimated_minutes"] <= 45
    assert len(large["items"]) > len(small["items"])


def test_a_budget_too_small_for_anything_still_serves_one_item():
    """Better a session that runs long than a session with nothing in it."""
    plan = build_plan("coding", 1)
    assert len(plan["items"]) == 1


def test_planning_is_deterministic():
    assert plan_item_ids(build_plan("coding", 90)) == plan_item_ids(build_plan("coding", 90))


def test_difficulty_bias_moves_which_item_comes_first():
    harder = build_plan("coding", 45, difficulty_bias=1.0)
    easier = build_plan("coding", 45, difficulty_bias=-1.0)

    assert harder["items"][0]["elo"] > easier["items"][0]["elo"]
    assert harder["target_elo"] > easier["target_elo"]


def test_focus_concepts_narrow_the_pool():
    plan = build_plan("coding", 90, focus_concepts=("monotonic-stack",))
    ids = plan_item_ids(plan)

    assert ids
    assert all("monotonic-stack" in eligible_by_id()[item_id].concepts for item_id in ids)


def test_a_focus_nothing_matches_plans_nothing():
    """An empty plan is a refusal the session layer turns into a 422, not a session with
    no items in it."""
    assert build_plan("coding", 45, focus_concepts=("no-such-concept",))["items"] == []


def eligible_by_id():
    return {item.id: item for item in eligible_items("coding")}
