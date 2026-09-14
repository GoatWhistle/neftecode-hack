"""Looking past the horizon: time to a quality violation and an early, still-gated choice."""
import json
from pathlib import Path

import pandas as pd
import pytest

from neftecode.application.services.explain import explain
from neftecode.application.use_cases.make_decision import MakeDecision
from neftecode.application.use_cases.plan_operation import PlanCandidate, PlanOperation, PlanStep
from neftecode.infrastructure.config.scenario import load_scenario, parse_scenario
from neftecode.infrastructure.live.advisor import bind_forecast

BASELINE = Path("config/scenarios/baseline.json")
SOUR = Path("config/scenarios/sour_crude.json")


def measured(level, decision_time="2026-03-01T12:00:00"):
    when = pd.Timestamp(decision_time)
    return {"decision_time": decision_time, "origin": "real_measurements_at_decision_time",
            "quality_history_hours": 72, "pak_expected_per_hour": 6.0,
            "pak_trusted_hourly": [[(when.floor("h") - pd.Timedelta(value=h, unit="h")).isoformat(), level, 6]
                                   for h in range(72)],
            "lab_recent": []}


def live_scenario(level, inflow):
    raw = json.loads(BASELINE.read_text())
    forecast = {"model": "test", "value": inflow - 1, "lower": inflow - 2, "upper": inflow,
                "available": True, "reason": "test"}
    bound = bind_forecast(raw, forecast, state=measured(level))
    return parse_scenario(bound), bound


def hold_plan(planner, scenario):
    operation = scenario.current_operation
    recipe = {t.tank_id: float(operation.recipe.get(t.tank_id, 0.0)) for t in scenario.tanks}
    return PlanCandidate("hold", (PlanStep(0.0, planner.base_controls(), recipe, operation.throughput.value),))


def test_the_horizon_alone_hides_a_violation_the_projection_finds():
    scenario, _ = live_scenario(9.6, 16.0)
    planner = PlanOperation(scenario)
    plan = hold_plan(planner, scenario)
    assert planner.evaluate(plan).feasible, "в пределах 3 ч режим допустим"
    projected = planner.lookahead(plan, 48.0)
    assert projected["constraint"] == "quality.sulfur_mgkg"
    assert 3.0 < projected["hours_to_violation"] < 12.0


def test_a_clean_inflow_shows_no_violation_ahead():
    scenario, _ = live_scenario(7.0, 8.0)
    planner = PlanOperation(scenario)
    projected = planner.lookahead(hold_plan(planner, scenario), 48.0)
    assert projected["hours_to_violation"] is None


def test_the_projection_stops_where_a_stock_runs_out():
    scenario = load_scenario(SOUR)
    decision = MakeDecision(scenario).decide(budget=400)
    stock = decision["lookahead"]["selected"]["stock_ends_at_hours"]
    assert stock is not None and 3.0 <= stock < 51.0


def test_an_early_violation_changes_the_choice_without_waiving_the_gate():
    scenario, raw = live_scenario(9.6, 16.0)
    decision = MakeDecision(scenario).decide(budget=400, raw_scenario=raw)
    look = decision["lookahead"]
    assert look["initial"]["hours_to_violation"] < 12.0
    assert look["switched"] is True
    assert decision["status"] == "recommend_scenario"
    assert decision["gate"]["feasible"] is True
    remaining = look["selected"]["hours_to_violation"]
    assert remaining is None or remaining > look["initial"]["hours_to_violation"]
    text = [s["text"] for s in explain(decision, scenario)["statements"] if s["topic"] == "lookahead"]
    assert text and "За горизонтом" in text[0]


def test_without_a_policy_nothing_is_projected():
    scenario, raw = live_scenario(9.6, 16.0)
    for key in ("lookahead_hours", "min_reaction_hours"):
        raw["policy"].pop(key)
    decision = MakeDecision(parse_scenario(raw)).decide(budget=200, raw_scenario=raw)
    assert decision["lookahead"] is None
    assert decision["status"] == "hold"


def test_an_unavoidable_violation_is_warned_not_refused():
    scenario, raw = live_scenario(9.6, 16.0)
    raw["policy"]["min_reaction_hours"] = 48.0          # no feasible plan can keep spec that long
    decision = MakeDecision(parse_scenario(raw)).decide(budget=400, raw_scenario=raw)
    look = decision["lookahead"]
    assert decision["status"] != "refuse"
    selected = look["selected"]
    reach = selected["hours_to_violation"] if selected["hours_to_violation"] is not None else selected["stock_ends_at_hours"]
    assert reach is not None and reach < 48.0
    assert look["warning"] and "Предупреждение" in decision["reason"]
