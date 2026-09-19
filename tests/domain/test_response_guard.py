import json
from pathlib import Path

import pytest

from neftecode.application.use_cases.make_decision import MakeDecision
from neftecode.application.use_cases.plan_operation import PlanCandidate
from neftecode.domain.advisory.entities import PlanStep
from neftecode.domain.advisory.response_guard import (moves_hydrotreating, moves_temperature, weak_response_factor,
                                                      weak_response_raw)
from neftecode.evaluation.robustness import RobustnessCheck
from neftecode.infrastructure.config.scenario import parse_scenario
from neftecode.infrastructure.live.advisor import bind_forecast, bind_measurements

BASELINE = Path("config/scenarios/baseline.json")
DENSITY = {"density_kgm3": 836.1}


def response(**overrides):
    base = {"schema_version": "v1", "tag": "ht.T6", "flow_tag": "ht.F9", "tau": "2026-01-01", "window_months": 12,
            "beta_mgkg_per_c": -0.4332, "ci": [-0.4761, -0.397], "envelope_dt_c": 2.0, "n_rows": 48938,
            "method": "тест", "drift": [], "flow_beta": None, "model_fingerprint": "x",
            "t6_range_c": [342.9, 386.1], "f9_range_tph": [150.3, 256.7], "weak_strong": [-0.217, -0.739]}
    return {**base, **overrides}


def measured():
    return {tag: {"value": value, "time": "2026-01-05T08:00:00", "age_min": 0.0, "max_age_min": 30.0}
            for tag, value in (("ht.T6", 367.8), ("ht.F9", 206.1), ("ht.F26", 244.1))}


def forecast(upper):
    return {"model": "last_pak", "value": 6.0, "lower": 4.0, "upper": upper, "available": True, "reason": "тест"}


SCENARIO_LAG = {"response_onset_hours": 2.0, "horizon_response_share": 1.0}


def knife_edge(light: bool = False, tank_sulfur: float = 9.34, upper: float = 10.6, **response_overrides) -> dict:
    raw = json.loads(BASELINE.read_text(encoding="utf-8"))
    for tank in raw["tanks"]:
        if tank["tank_id"] == "main":
            tank["inventory"]["value"] = 600.0
            tank["properties"]["sulfur_mgkg"]["value"] = tank_sulfur
        if tank["tank_id"] == "reserve":
            tank["available"] = False
        if tank["tank_id"] == "light" and light:
            tank["available"] = True
            tank["cost_per_t"]["value"] = 5.0
            tank["properties"]["cetane_number"] = {"value": 52.0, "unit": "ед.", "source": "scenario"}
    for spec in raw["stages"]["avt"]["controls"].values():
        spec["step"]["value"] = 0.0
    if light:
        raw["policy"]["lookahead_hours"] = 0.0
    bound = bind_measurements(raw, measured(), DENSITY, response(**response_overrides), forecast(upper))
    return bind_forecast(bound, forecast(upper))


def decide(bound: dict) -> dict:
    scenario = parse_scenario(bound)
    return MakeDecision(scenario, robustness_evaluator=RobustnessCheck(
        scenario, bound, scenario_parser=parse_scenario)).decide(budget=800, raw_scenario=bound)


def guard_trace(decision: dict) -> list[tuple[str, str]]:
    return [(t["plan"], t["outcome"]) for t in decision["trace"] if t["agent"] == "response_guard"]



def test_the_weak_edge_scales_the_bound_slope_by_weak_over_beta():
    bound = knife_edge()
    model = bound["stages"]["hydrotreating"]["model"]
    weak = weak_response_raw(bound)["stages"]["hydrotreating"]["model"]
    assert weak_response_factor(bound) == pytest.approx(0.217 / 0.4332)
    assert weak["conversion_per_degree"] == pytest.approx(model["conversion_per_degree"] * 0.217 / 0.4332)
    assert weak["beta_mgkg_per_c"] == pytest.approx(-0.217)
    assert bound["stages"]["hydrotreating"]["model"]["conversion_per_degree"] == model["conversion_per_degree"]


def test_without_a_data_driven_slope_there_is_no_weak_edge():
    assert weak_response_raw(json.loads(BASELINE.read_text(encoding="utf-8"))) is None
    assert weak_response_raw(knife_edge(weak_strong=None)) is None
    assert weak_response_raw(knife_edge(weak_strong=[0.1, -0.7])) is None, "край другого знака — не край"


def test_a_plan_moves_the_temperature_only_when_a_step_or_a_confirmed_move_changes_it():
    base = {"ht_reactor_inlet_temp_c": 367.8, "ht_feed_flow_m3h": 246.5}
    hold = PlanCandidate("hold", (PlanStep(0.0, dict(base), {"main": 1.0}, 100.0),), 0)
    warmer = PlanCandidate("w", (PlanStep(0.0, {**base, "ht_reactor_inlet_temp_c": 368.8}, {"main": 1.0}, 100.0),), 1)
    faster = PlanCandidate("f", (PlanStep(0.0, {**base, "ht_feed_flow_m3h": 250.0}, {"main": 1.0}, 100.0),), 1)
    assert not moves_temperature(hold, base) and not moves_hydrotreating(hold, base)
    assert moves_temperature(warmer, base) and moves_hydrotreating(warmer, base)
    assert not moves_temperature(faster, base) and moves_hydrotreating(faster, base)
    assert moves_temperature(hold, base, confirmed=((-1.0, {"ht_reactor_inlet_temp_c": 369.0}),))



def test_a_temperature_move_that_fails_at_the_weak_edge_is_not_selected():
    without_guard = decide(knife_edge(weak_strong=None, **SCENARIO_LAG))
    assert without_guard["status"] == "recommend_scenario"
    assert without_guard["selected_plan"]["steps"][0]["controls"]["ht_reactor_inlet_temp_c"] == pytest.approx(368.8)
    assert guard_trace(without_guard) == []

    with_guard = decide(knife_edge(**SCENARIO_LAG))
    assert with_guard["status"] == "refuse"
    assert with_guard["refusal"]["kind"] == "weak_response_failed"
    assert with_guard["refusal"]["plan_id"] == without_guard["selected_plan"]["plan_id"]
    assert any("нарушает предел 10" in example for example in with_guard["refusal"]["examples"])
    entry = next(t for t in with_guard["trace"] if t["agent"] == "response_guard")
    assert entry["outcome"] == "violated" and entry["beta_weak"] == pytest.approx(-0.217)


def test_after_the_veto_the_next_feasible_plan_is_released():
    decision = decide(knife_edge(light=True, **SCENARIO_LAG))
    assert decision["status"] == "recommend_scenario"
    selected = decision["selected_plan"]
    assert selected["steps"][0]["controls"]["ht_reactor_inlet_temp_c"] == pytest.approx(367.8)
    trace = guard_trace(decision)
    assert trace[0][1] == "violated" and trace[0][0] != selected["plan_id"]
    assert trace[-1] == (selected["plan_id"], "not_applicable")


def test_a_move_justified_only_past_the_horizon_must_keep_its_promise_at_the_weak_edge():
    without_guard = decide(knife_edge(tank_sulfur=9.3, upper=10.3, weak_strong=None))
    assert without_guard["status"] == "recommend_scenario"
    assert without_guard["lookahead"]["switched"] is True
    assert without_guard["selected_plan"]["steps"][0]["controls"]["ht_reactor_inlet_temp_c"] == pytest.approx(368.8)

    with_guard = decide(knife_edge(tank_sulfur=9.3, upper=10.3))
    selected = with_guard["selected_plan"]
    assert selected["plan_id"] != without_guard["selected_plan"]["plan_id"]
    assert selected["steps"][0]["controls"]["ht_reactor_inlet_temp_c"] == pytest.approx(367.8)
    trace = guard_trace(with_guard)
    assert trace[0] == (without_guard["selected_plan"]["plan_id"], "violated")
    assert trace[-1] == (selected["plan_id"], "not_applicable")
    entry = next(t for t in with_guard["trace"] if t["agent"] == "response_guard")
    assert entry["lookahead_hours_to_violation"] is None
    assert entry["weak_lookahead_hours_to_violation"] is not None
    assert entry["weak_lookahead_hours_to_violation"] < 12.0
    assert "раньше запаса реакции 12 ч" in entry["violations"][0]


def test_a_hold_is_not_checked_against_the_weak_edge():
    raw = json.loads(BASELINE.read_text(encoding="utf-8"))
    bound = bind_forecast(bind_measurements(raw, measured(), DENSITY, response(), forecast(9.0)), forecast(9.0))
    decision = decide(bound)
    assert decision["status"] == "hold"
    assert guard_trace(decision) == [("hold", "not_applicable")]


def test_scenario_decisions_without_data_driven_slope_carry_no_guard_entry():
    raw = json.loads(BASELINE.read_text(encoding="utf-8"))
    scenario = parse_scenario(raw)
    decision = MakeDecision(scenario, robustness_evaluator=RobustnessCheck(
        scenario, raw, scenario_parser=parse_scenario)).decide(budget=400, raw_scenario=raw)
    assert guard_trace(decision) == []
