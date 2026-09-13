"""Costs counted once, and a severity index that never becomes a claim about equipment life."""
import json
from pathlib import Path

import pytest

from neftecode.domain.production.economics import SEVERITY_TERMS, Economics, EconomicsError
from neftecode.infrastructure.config.scenario import load_scenario, parse_scenario

BASELINE = Path("config/scenarios/baseline.json")


def economics(**policy):
    raw = json.loads(BASELINE.read_text())
    if policy:
        raw["policy"].update(policy)
    return Economics(parse_scenario(raw))


REFERENCE_TEMP = 348.0
REFERENCE_FLOW = 256.0


# --- Hand-checked cost arithmetic ---

def test_component_cost_matches_hand_computation():
    step = economics().step_cost({"main": 0.9, "reserve": 0.1}, 100.0, 1.0, ht_temp_c=REFERENCE_TEMP)
    assert step.component_cost == pytest.approx(100 * 0.9 * 1.0 + 100 * 0.1 * 1.4)


def test_treating_cost_at_the_reference_temperature_is_the_reference_price():
    step = economics().step_cost({"main": 1.0}, 100.0, 1.0, ht_temp_c=REFERENCE_TEMP)
    assert step.treating_cost == pytest.approx(100 * 0.05)


def test_deeper_treating_costs_more_by_the_declared_slope():
    step = economics().step_cost({"main": 1.0}, 100.0, 1.0, ht_temp_c=REFERENCE_TEMP + 10)
    assert step.treating_cost == pytest.approx(100 * (0.05 + 0.004 * 10))


def test_treating_below_the_reference_is_not_cheaper_than_the_reference():
    cold = economics().step_cost({"main": 1.0}, 100.0, 1.0, ht_temp_c=REFERENCE_TEMP - 10)
    assert cold.treating_cost == pytest.approx(100 * 0.05)


def test_additive_cost_uses_its_declared_price():
    step = economics().step_cost({"main": 1.0}, 100.0, 1.0, additive_dose=0.02,
                                 ht_temp_c=REFERENCE_TEMP)
    assert step.additive_cost == pytest.approx(100 * 0.02 * 100.0)


def test_the_expensive_additive_dominates_the_bill():
    plain = economics().step_cost({"main": 1.0}, 100.0, 1.0, ht_temp_c=REFERENCE_TEMP)
    dosed = economics().step_cost({"main": 1.0}, 100.0, 1.0, additive_dose=0.02,
                                  ht_temp_c=REFERENCE_TEMP)
    assert dosed.total > 2 * plain.total


def test_more_reserve_costs_more_because_the_reserve_is_dearer():
    cheap = economics().step_cost({"main": 1.0}, 100.0, 1.0, ht_temp_c=REFERENCE_TEMP)
    rich = economics().step_cost({"main": 0.5, "reserve": 0.5}, 100.0, 1.0, ht_temp_c=REFERENCE_TEMP)
    assert rich.component_cost > cheap.component_cost


def test_cost_scales_with_the_mass_actually_produced():
    one = economics().step_cost({"main": 1.0}, 100.0, 1.0, ht_temp_c=REFERENCE_TEMP)
    two = economics().step_cost({"main": 1.0}, 100.0, 2.0, ht_temp_c=REFERENCE_TEMP)
    assert two.total == pytest.approx(2 * one.total)


# --- Nothing is counted twice ---

def test_total_is_exactly_the_sum_of_its_three_parts():
    step = economics().step_cost({"main": 0.8, "reserve": 0.2}, 100.0, 1.5, additive_dose=0.01,
                                 ht_temp_c=REFERENCE_TEMP + 5)
    assert step.total == pytest.approx(step.component_cost + step.additive_cost + step.treating_cost)


def test_per_tonne_and_horizon_totals_are_reported_separately():
    e = economics()
    steps = [e.step_cost({"main": 1.0}, 100.0, 1.0, ht_temp_c=REFERENCE_TEMP) for _ in range(3)]
    summary = e.summarise(steps)
    assert summary["production_t"] == pytest.approx(300.0)
    assert summary["total_cost"] == pytest.approx(sum(s.total for s in steps))
    assert summary["cost_per_tonne"] == pytest.approx(summary["total_cost"] / 300.0)


def test_summary_parts_add_up_to_the_total():
    e = economics()
    steps = [e.step_cost({"main": 0.9, "reserve": 0.1}, 100.0, 1.0, additive_dose=0.01,
                         ht_temp_c=REFERENCE_TEMP + 3)]
    summary = e.summarise(steps)
    assert summary["total_cost"] == pytest.approx(
        summary["component_cost"] + summary["additive_cost"] + summary["treating_cost"])


def test_zero_production_gives_no_cost_per_tonne_rather_than_dividing_by_zero():
    step = economics().step_cost({"main": 1.0}, 0.0, 1.0, ht_temp_c=REFERENCE_TEMP)
    assert step.per_tonne is None
    assert economics().summarise([step])["cost_per_tonne"] is None


@pytest.mark.parametrize("value", [-1.0, float("nan")])
def test_impossible_inputs_are_refused(value):
    with pytest.raises(EconomicsError, match="конечным и неотрицательным"):
        economics().step_cost({"main": 1.0}, value, 1.0)


def test_summary_states_that_the_units_are_conditional():
    summary = economics().summarise([economics().step_cost({"main": 1.0}, 100.0, 1.0,
                                                           ht_temp_c=REFERENCE_TEMP)])
    assert "не измеренная экономия" in summary["scope"]
    assert "не входит в сумму дважды" in summary["rule"]


# --- Severity: a described index, nothing more ---

def test_severity_is_zero_at_the_reference_regime():
    result = economics().severity({"ht_reactor_inlet_temp_c": REFERENCE_TEMP,
                                   "ht_feed_flow_m3h": REFERENCE_FLOW})
    assert result["index"] == pytest.approx(0.0)
    assert result["available"] is True


def test_hotter_reactor_raises_severity():
    e = economics()
    base = e.severity({"ht_reactor_inlet_temp_c": REFERENCE_TEMP, "ht_feed_flow_m3h": REFERENCE_FLOW})
    hot = e.severity({"ht_reactor_inlet_temp_c": REFERENCE_TEMP + 12, "ht_feed_flow_m3h": REFERENCE_FLOW})
    assert hot["index"] > base["index"]


def test_higher_throughput_raises_severity():
    e = economics()
    base = e.severity({"ht_reactor_inlet_temp_c": REFERENCE_TEMP, "ht_feed_flow_m3h": REFERENCE_FLOW})
    fast = e.severity({"ht_reactor_inlet_temp_c": REFERENCE_TEMP, "ht_feed_flow_m3h": REFERENCE_FLOW + 30})
    assert fast["index"] > base["index"]


def test_severity_below_the_reference_does_not_go_negative():
    result = economics().severity({"ht_reactor_inlet_temp_c": REFERENCE_TEMP - 15,
                                   "ht_feed_flow_m3h": REFERENCE_FLOW - 50})
    assert result["index"] == pytest.approx(0.0)


def test_every_term_of_the_index_is_visible():
    result = economics().severity({"ht_reactor_inlet_temp_c": REFERENCE_TEMP + 18,
                                   "ht_feed_flow_m3h": REFERENCE_FLOW + 22})
    assert set(result["terms"]) == set(SEVERITY_TERMS)
    assert result["weights"], "веса обязаны быть видны, а не спрятаны в коде"
    expected = sum(result["weights"][k] * v for k, v in result["terms"].items())
    assert result["index"] == pytest.approx(expected)


def test_weights_come_from_the_scenario_when_declared():
    result = economics(severity_weights={"temperature_above_reference": 1.0,
                                         "throughput_above_reference": 0.0}).severity(
        {"ht_reactor_inlet_temp_c": REFERENCE_TEMP + 18, "ht_feed_flow_m3h": REFERENCE_FLOW + 22})
    assert result["index"] == pytest.approx(result["terms"]["temperature_above_reference"])


def test_an_unknown_severity_term_is_refused():
    with pytest.raises(EconomicsError, match="неизвестные слагаемые"):
        economics(severity_weights={"catalyst_age": 1.0}).severity(
            {"ht_reactor_inlet_temp_c": REFERENCE_TEMP, "ht_feed_flow_m3h": REFERENCE_FLOW})


def test_unknown_setpoints_leave_severity_unavailable_rather_than_zero():
    result = economics().severity({"ht_reactor_inlet_temp_c": None, "ht_feed_flow_m3h": REFERENCE_FLOW})
    assert result["available"] is False
    assert result["index"] is None


def test_missing_reference_point_leaves_severity_unavailable():
    raw = json.loads(BASELINE.read_text())
    del raw["stages"]["hydrotreating"]["model"]["reference_temp_c"]
    result = Economics(parse_scenario(raw)).severity(
        {"ht_reactor_inlet_temp_c": REFERENCE_TEMP, "ht_feed_flow_m3h": REFERENCE_FLOW})
    assert result["available"] is False


def test_severity_denies_being_a_statement_about_equipment_life():
    result = economics().severity({"ht_reactor_inlet_temp_c": REFERENCE_TEMP,
                                   "ht_feed_flow_m3h": REFERENCE_FLOW})
    assert "не возраст катализатора" in result["scope"]
    assert "не вероятность отказа" in result["scope"]
