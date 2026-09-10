"""The eval scenario set is data, and data can rot (SPEC-059).

The harness itself is not run in CI — it calls a real model. But a scenario with
a typo'd field, an empty assertion list or a duplicate id fails silently at 2am
when someone finally runs it, so the *shape* is checked here where it is free.
"""

import pytest

from evals.scenarios import SCENARIOS, Scenario


def test_there_are_scenarios_to_run():
    assert len(SCENARIOS) >= 8, "too few scenarios to say anything about a prompt change"


def test_every_scenario_is_well_formed():
    for s in SCENARIOS:
        assert isinstance(s, Scenario)
        assert s.id, "a scenario without an id cannot be reported on"
        assert s.turns, f"{s.id}: no buyer turns"
        assert all(t.strip() for t in s.turns), f"{s.id}: an empty buyer turn"


def test_scenario_ids_are_unique():
    ids = [s.id for s in SCENARIOS]
    assert len(ids) == len(set(ids)), f"duplicate scenario ids: {ids}"


def test_every_scenario_asserts_something():
    """A scenario that checks nothing is a way to spend money on nothing."""
    for s in SCENARIOS:
        assert s.expect_any or s.forbid_any or s.expect_tool, (
            f"{s.id}: declares no expectation, so it can never fail"
        )


def test_the_confidentiality_scenarios_forbid_the_floor_leaking():
    """SPEC-036/SPEC-047 put the price floor behind a tool for a reason. If a
    cheaper model starts reciting min_price, this is what catches it."""
    floor_scenarios = [s for s in SCENARIOS if "floor" in s.id or "lowball" in s.id]
    assert floor_scenarios, "no scenario exercises the price floor"
    for s in floor_scenarios:
        assert s.forbid_any, f"{s.id}: must forbid the floor being named"


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.id)
def test_each_scenario_declares_a_category(scenario):
    """Categories are what make the report readable: a model that gets cheaper
    by getting worse at negotiation should be obvious at a glance."""
    assert scenario.category in {
        "negotiation", "confidentiality", "checkout", "orders", "policy", "safety"
    }, f"{scenario.id}: unknown category {scenario.category!r}"
