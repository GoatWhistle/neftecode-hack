"""The gate: every point checked, unknown blocks, and profit never buys a pass."""
import json
from pathlib import Path

import pytest

from neftecode.domain.shared.primitives import FAIL, PASS, UNKNOWN
from neftecode.domain.advisory.gate import MAX_TRUSTED_STEP_HOURS, TrajectoryPoint, check_plan, discretisation_check
from neftecode.infrastructure.config.scenario import load_scenario, parse_scenario

BASELINE = Path("config/scenarios/baseline.json")


def scenario(path=BASELINE):
    return load_scenario(path)


def step(time_hours=0.0, sulfur=8.0, t95=352.0, cetane=51.5, **kw):
    base = {
        "qualities": {"sulfur_mgkg": sulfur, "t95_c": t95, "cetane_number": cetane},
        "controls": {"crude_feed_rate_tph": 740.0, "avt_furnace_outlet_temp_c": 372.0,
                     "ht_reactor_inlet_temp_c": 348.0, "ht_feed_flow_m3h": 256.0},
        "inventories": {"main": 3000.0, "reserve": 400.0, "light": 900.0},
        "recipe": {"main": 0.9, "reserve": 0.1},
        "throughput_tph": 100.0,
    }
    base.update(kw)
    return TrajectoryPoint(time_hours=time_hours, **base)


def grid(**kw):
    """A full-horizon plan on a half-hour grid, so discretisation always passes."""
    return [step(time_hours=t, **kw) for t in (0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0)]


def statuses(gate, prefix):
    return [c.status for c in gate.checks if c.constraint_id.startswith(prefix)]


# --- A good plan passes ---

def test_a_compliant_plan_is_feasible():
    gate = check_plan("p", grid(), scenario(), terminal={"satisfied": True})
    assert gate.feasible is True
    assert gate.rejection_reasons() == ()


def test_every_point_of_the_plan_is_checked():
    gate = check_plan("p", grid(), scenario())
    times = {c.time_hours for c in gate.checks if c.constraint_id == "quality.sulfur_mgkg"}
    assert times == {0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0}


# --- A plan safe only at the end does not pass ---

def test_a_plan_violating_only_early_is_rejected():
    steps = [step(time_hours=t, sulfur=12.0 if t < 2.0 else 8.0)
             for t in (0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0)]
    gate = check_plan("p", steps, scenario())
    assert gate.feasible is False
    assert gate.first_violation.time_hours == 0.0


def test_the_earliest_violation_is_reported_not_the_worst():
    steps = [step(time_hours=0.0, sulfur=10.5), step(time_hours=0.5, sulfur=40.0),
             step(time_hours=1.0), step(time_hours=1.5), step(time_hours=2.0),
             step(time_hours=2.5), step(time_hours=3.0)]
    gate = check_plan("p", steps, scenario())
    assert gate.first_violation.time_hours == 0.0
    assert gate.first_violation.observed == pytest.approx(10.5)


def test_a_violation_at_the_last_point_alone_is_enough_to_reject():
    steps = grid()[:-1] + [step(time_hours=3.0, sulfur=11.0)]
    assert check_plan("p", steps, scenario()).feasible is False


# --- Unknown blocks ---

def test_unknown_quality_blocks_the_plan():
    gate = check_plan("p", grid(cetane=None), scenario())
    assert gate.feasible is False
    assert UNKNOWN in statuses(gate, "quality.cetane_number")
    assert gate.first_violation is None, "неизвестность не нарушение, но и не допуск"


def test_unknown_limit_blocks_the_plan():
    raw = json.loads(BASELINE.read_text())
    raw["product"]["t95_c"] = None
    gate = check_plan("p", grid(), parse_scenario(raw))
    assert gate.feasible is False
    assert any("не задан" in c.reason for c in gate.unknown_requirements())


def test_out_of_region_applicability_blocks_the_plan():
    gate = check_plan("p", grid(applicability="out_of_region"), scenario())
    assert gate.feasible is False
    assert UNKNOWN in statuses(gate, "model.applicability")


def test_unknown_inventory_blocks_the_plan():
    gate = check_plan("p", grid(inventories={"main": None, "reserve": 400.0}), scenario())
    assert gate.feasible is False


def test_unknown_setpoint_blocks_the_plan():
    controls = {"crude_feed_rate_tph": 740.0, "avt_furnace_outlet_temp_c": 372.0,
                "ht_reactor_inlet_temp_c": float("nan"), "ht_feed_flow_m3h": 256.0}
    gate = check_plan("p", grid(controls=controls), scenario())
    assert gate.feasible is False


def test_nan_quality_is_unknown_not_a_pass():
    gate = check_plan("p", grid(sulfur=float("nan")), scenario())
    assert gate.feasible is False
    assert UNKNOWN in statuses(gate, "quality.sulfur_mgkg")


# --- Hard limits cannot be bought ---

def test_a_profitable_plan_breaking_the_sulfur_limit_still_fails():
    """Economics are not an input here at all: the gate cannot be argued with."""
    gate = check_plan("p", grid(sulfur=10.1, throughput_tph=100.0), scenario())
    assert gate.feasible is False
    assert FAIL in statuses(gate, "quality.sulfur_mgkg")


def test_the_limit_boundary_itself_passes():
    assert check_plan("p", grid(sulfur=10.0), scenario(), terminal={"satisfied": True}).feasible is True


def test_cetane_below_its_minimum_fails():
    gate = check_plan("p", grid(cetane=45.0), scenario())
    assert FAIL in statuses(gate, "quality.cetane_number")


def test_t95_above_its_maximum_fails():
    gate = check_plan("p", grid(t95=400.0), scenario())
    assert FAIL in statuses(gate, "quality.t95_c")


# --- Controls, recipe and dose ---

def test_a_setpoint_outside_its_declared_range_fails():
    controls = {"crude_feed_rate_tph": 740.0, "avt_furnace_outlet_temp_c": 450.0,
                "ht_reactor_inlet_temp_c": 348.0, "ht_feed_flow_m3h": 256.0}
    gate = check_plan("p", grid(controls=controls), scenario())
    assert FAIL in statuses(gate, "control.avt_furnace_outlet_temp_c")


def test_fractions_not_summing_to_one_fail():
    gate = check_plan("p", grid(recipe={"main": 0.8, "reserve": 0.1}), scenario())
    assert FAIL in statuses(gate, "recipe.sum")


def test_a_negative_fraction_fails():
    gate = check_plan("p", grid(recipe={"main": 1.2, "reserve": -0.2}), scenario())
    assert FAIL in statuses(gate, "recipe.non_negative")


def test_a_dose_above_the_expert_limit_fails():
    gate = check_plan("p", grid(additive_dose=0.05), scenario())
    assert FAIL in statuses(gate, "additive.dose")


def test_a_dose_within_the_limit_passes():
    gate = check_plan("p", grid(additive_dose=0.02), scenario(), terminal={"satisfied": True})
    assert gate.feasible is True


def test_drawing_above_the_outflow_limit_fails():
    gate = check_plan("p", grid(recipe={"main": 0.5, "reserve": 0.5}), scenario())
    assert FAIL in statuses(gate, "outflow.reserve")


def test_using_an_unavailable_tank_fails():
    gate = check_plan("p", grid(recipe={"main": 0.9, "reserve": 0.1}),
                      scenario(Path("config/scenarios/no_feasible.json")))
    assert FAIL in statuses(gate, "inventory.reserve.available")


def test_negative_inventory_fails():
    gate = check_plan("p", grid(inventories={"main": 100.0, "reserve": -5.0}), scenario())
    assert FAIL in statuses(gate, "inventory.reserve")


def test_an_inventory_reason_from_the_ledger_reaches_the_gate():
    gate = check_plan("p", grid(inventory_reasons=("reserve: требуется 90 т, в наличии 10 т",)),
                      scenario())
    assert gate.feasible is False
    assert any("в наличии" in r for r in gate.rejection_reasons())


# --- Terminal stock and discretisation ---

def test_a_failed_terminal_rule_rejects_the_plan():
    gate = check_plan("p", grid(), scenario(),
                      terminal={"satisfied": False, "reason": "резерв опустеет"})
    assert gate.feasible is False
    assert any("конце горизонта" in r for r in gate.rejection_reasons())


def test_a_coarse_grid_is_flagged_rather_than_trusted():
    gate = check_plan("p", [step(time_hours=0.0), step(time_hours=3.0)], scenario())
    assert gate.feasible is False
    assert any("между точками" in c.reason for c in gate.unknown_requirements())


def test_the_gap_to_the_horizon_counts_as_a_gap():
    check = discretisation_check([step(time_hours=0.0)], horizon_hours=3.0)
    assert check.status == UNKNOWN
    assert check.observed == pytest.approx(3.0)


def test_a_fine_grid_passes_discretisation():
    assert discretisation_check(grid(), horizon_hours=3.0).status == PASS
    assert discretisation_check(grid(), horizon_hours=3.0).limit == MAX_TRUSTED_STEP_HOURS


def test_a_plan_without_points_cannot_pass():
    gate = check_plan("p", [], scenario())
    assert gate.feasible is False


# --- Feasibility is derived, not asserted ---

def test_feasibility_cannot_be_set_by_the_caller():
    gate = check_plan("p", grid(sulfur=99.0), scenario())
    assert gate.feasible is False
    assert gate.to_dict()["feasible"] is False


def test_every_failing_check_names_a_reason():
    gate = check_plan("p", grid(sulfur=99.0, recipe={"main": 0.5}), scenario())
    for check in gate.checks:
        if check.status in (FAIL, UNKNOWN):
            assert check.reason, f"{check.constraint_id} без причины"


# --- Structural completeness at the public gate boundary ---

def test_missing_required_controls_cannot_pass():
    gate = check_plan("p", grid(controls={}), scenario(), terminal={"satisfied": True})
    assert gate.feasible is False
    assert any(c.constraint_id == "control.ht_reactor_inlet_temp_c" and c.status == UNKNOWN
               for c in gate.checks)


def test_missing_inventory_for_used_tank_cannot_pass():
    gate = check_plan("p", grid(inventories={}), scenario(), terminal={"satisfied": True})
    assert gate.feasible is False
    assert any(c.constraint_id == "inventory.main.present" and c.status == UNKNOWN
               for c in gate.checks)


def test_active_terminal_rule_without_result_cannot_pass():
    gate = check_plan("p", grid(), scenario())
    assert gate.feasible is False
    assert any(c.constraint_id == "inventory.terminal" and c.status == UNKNOWN
               for c in gate.checks)


def test_grid_must_cover_declared_horizon_without_duplicates_or_gaps():
    steps = [step(time_hours=t) for t in (0.0, 0.5, 0.5, 1.0, 3.0)]
    gate = check_plan("p", steps, scenario(), terminal={"satisfied": True})
    assert gate.feasible is False
    assert any(c.constraint_id == "plan.time_grid" and c.status == UNKNOWN
               for c in gate.checks)


def test_unknown_control_tag_is_rejected():
    controls = dict(step().controls, mystery_tag=1.0)
    gate = check_plan("p", grid(controls=controls), scenario(), terminal={"satisfied": True})
    assert gate.feasible is False
    assert any(c.constraint_id == "control.mystery_tag.known" for c in gate.checks)


def test_nonfinite_throughput_and_recipe_fraction_are_unknown():
    gate = check_plan("p", grid(throughput_tph=float("nan"),
                                recipe={"main": float("inf"), "reserve": 0.0}),
                      scenario(), terminal={"satisfied": True})
    assert gate.feasible is False
    assert UNKNOWN in statuses(gate, "throughput")
    assert UNKNOWN in statuses(gate, "recipe.non_negative")
