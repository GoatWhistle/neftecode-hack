import json
from pathlib import Path

import pytest

from neftecode.domain.production.economics import SEVERITY_TERMS, Economics, EconomicsError
from neftecode.infrastructure.config.scenario import load_scenario, parse_scenario

BASELINE = Path("config/scenarios/baseline.json")


def economics(**policy):
    raw = json.loads(BASELINE.read_text(encoding="utf-8"))
    if policy:
        raw["policy"].update(policy)
    return Economics(parse_scenario(raw))


REFERENCE_TEMP = 348.0
REFERENCE_FLOW = 256.0



def test_component_cost_matches_hand_computation():
    step = economics().step_cost({"main": 0.9, "reserve": 0.1}, 100.0, 1.0, ht_temp_c=REFERENCE_TEMP)
    reserve_price = 1.0 + 0.05 + 0.01 * (8.0 - 2.0) ** 2
    assert step.component_cost == pytest.approx(100 * 0.9 * 1.0 + 100 * 0.1 * reserve_price)


def test_treating_cost_at_the_reference_temperature_is_the_reference_price():
    step = economics().step_cost({"main": 1.0}, 100.0, 1.0, ht_temp_c=REFERENCE_TEMP)
    assert step.treating_cost == pytest.approx(100 * 0.05)


def test_deeper_treating_costs_more_by_the_declared_slope():
    step = economics().step_cost({"main": 1.0}, 100.0, 1.0, ht_temp_c=REFERENCE_TEMP + 10)
    depth = 0.42 * 10
    assert step.treating_cost == pytest.approx(100 * (0.05 + 0.01 * depth ** 2))


def test_doubling_the_treating_depth_quadruples_the_extra_energy():
    reference = economics().step_cost({"main": 1.0}, 100.0, 1.0, ht_temp_c=REFERENCE_TEMP).treating_cost
    shallow = economics().step_cost({"main": 1.0}, 100.0, 1.0, ht_temp_c=REFERENCE_TEMP + 5).treating_cost
    deep = economics().step_cost({"main": 1.0}, 100.0, 1.0, ht_temp_c=REFERENCE_TEMP + 10).treating_cost
    assert deep - reference == pytest.approx(4.0 * (shallow - reference))


def test_treating_below_the_reference_is_not_cheaper_than_the_reference():
    cold = economics().step_cost({"main": 1.0}, 100.0, 1.0, ht_temp_c=REFERENCE_TEMP - 10)
    assert cold.treating_cost == pytest.approx(100 * 0.05)


def test_additive_cost_uses_its_declared_price():
    step = economics().step_cost({"main": 1.0}, 100.0, 1.0, additive_dose=0.02,
                                 ht_temp_c=REFERENCE_TEMP)
    assert step.additive_cost == pytest.approx(100 * 0.02 * 10.0)


def test_the_expensive_additive_is_visible_in_the_bill():
    plain = economics().step_cost({"main": 1.0}, 100.0, 1.0, ht_temp_c=REFERENCE_TEMP)
    dosed = economics().step_cost({"main": 1.0}, 100.0, 1.0, additive_dose=0.02,
                                  ht_temp_c=REFERENCE_TEMP)
    assert dosed.total - plain.total == pytest.approx(100 * 0.02 * 10.0)


def test_more_reserve_costs_more_because_the_reserve_is_dearer():
    cheap = economics().step_cost({"main": 1.0}, 100.0, 1.0, ht_temp_c=REFERENCE_TEMP)
    rich = economics().step_cost({"main": 0.5, "reserve": 0.5}, 100.0, 1.0, ht_temp_c=REFERENCE_TEMP)
    assert rich.component_cost > cheap.component_cost


def test_cost_scales_with_the_mass_actually_produced():
    one = economics().step_cost({"main": 1.0}, 100.0, 1.0, ht_temp_c=REFERENCE_TEMP)
    two = economics().step_cost({"main": 1.0}, 100.0, 2.0, ht_temp_c=REFERENCE_TEMP)
    assert two.total == pytest.approx(2 * one.total)



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
    raw = json.loads(BASELINE.read_text(encoding="utf-8"))
    del raw["stages"]["hydrotreating"]["model"]["reference_temp_c"]
    result = Economics(parse_scenario(raw)).severity(
        {"ht_reactor_inlet_temp_c": REFERENCE_TEMP, "ht_feed_flow_m3h": REFERENCE_FLOW})
    assert result["available"] is False


def test_severity_denies_being_a_statement_about_equipment_life():
    result = economics().severity({"ht_reactor_inlet_temp_c": REFERENCE_TEMP,
                                   "ht_feed_flow_m3h": REFERENCE_FLOW})
    assert "не возраст катализатора" in result["scope"]
    assert "не вероятность отказа" in result["scope"]



def scenario_economics(path: str):
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return Economics(parse_scenario(raw)), raw


def reserve_price(raw: dict) -> float:
    econ = raw["economics"]
    sulfur = next(t for t in raw["tanks"] if t.get("on_demand"))["properties"]["sulfur_mgkg"]["value"]
    depth = max(0.0, econ["deep_treating_reference_mgkg"]["value"] - sulfur)
    return (econ["diesel_price_per_t"]["value"] + econ["treating_cost_per_t_at_reference"]["value"]
            + econ["deep_treating_cost_per_ppm2_per_t"]["value"] * depth ** 2)


@pytest.mark.parametrize("path,reference_temp", [
    ("config/scenarios/baseline.json", 348.0),
    ("config/scenarios/sour_crude.json", 348.0),
])
def test_a_step_with_an_on_demand_share_matches_hand_computed_cost(path, reference_temp):
    economics_of, raw = scenario_economics(path)
    base = raw["economics"]["treating_cost_per_t_at_reference"]["value"]
    main_price = next(t for t in raw["tanks"] if t["tank_id"] == "main")["cost_per_t"]["value"]
    recipe = {"main": 0.8, "reserve": 0.2}
    step = economics_of.step_cost(recipe, 100.0, 1.5, ht_temp_c=reference_temp)
    mass = 150.0
    expected_component = mass * 0.8 * main_price + mass * 0.2 * reserve_price(raw)
    expected_treating = mass * 0.8 * base
    assert step.component_cost == pytest.approx(expected_component)
    assert step.treating_cost == pytest.approx(expected_treating)
    assert step.total == pytest.approx(expected_component + expected_treating)


@pytest.mark.parametrize("path", ["config/scenarios/baseline.json", "config/scenarios/sour_crude.json"])
def test_base_treating_is_not_charged_twice_for_the_on_demand_share(path):
    economics_of, raw = scenario_economics(path)
    base = raw["economics"]["treating_cost_per_t_at_reference"]["value"]
    mass = 150.0
    step = economics_of.step_cost({"main": 0.8, "reserve": 0.2}, 100.0, 1.5, ht_temp_c=348.0)
    double_counted = mass * 0.2 * base
    assert step.treating_cost + double_counted == pytest.approx(mass * base)


def test_a_blend_without_the_on_demand_component_pays_base_treating_on_all_of_it():
    economics_of, raw = scenario_economics("config/scenarios/baseline.json")
    base = raw["economics"]["treating_cost_per_t_at_reference"]["value"]
    step = economics_of.step_cost({"main": 1.0}, 100.0, 1.0, ht_temp_c=348.0)
    assert step.treating_cost == pytest.approx(100.0 * base)


def test_a_blend_made_only_of_the_on_demand_component_pays_no_main_line_treating():
    economics_of, _ = scenario_economics("config/scenarios/baseline.json")
    step = economics_of.step_cost({"reserve": 1.0}, 100.0, 1.0, ht_temp_c=348.0)
    assert step.treating_cost == pytest.approx(0.0)
