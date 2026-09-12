"""Joining real measurements to the scenario advisor: the forecast must reach the decision."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from neftecode.data import series_frame
from neftecode.live import LiveError, bind_forecast, forecast_at, state_at
from neftecode.planner import Planner, PlanCandidate, PlanStepSpec
from neftecode.scenario import ScenarioError, load_scenario, parse_scenario

BASELINE = Path("config/scenarios/baseline.json")


def raw():
    return json.loads(BASELINE.read_text())


def forecast(value=12.0, upper=14.0, model="last_pak", available=True):
    return {"model": model, "value": value, "lower": value - 2, "upper": upper,
            "available": available, "reason": "тест"}


# --- Binding the forecast into the scenario ---

def test_the_upper_bound_is_what_is_bound_not_the_point_estimate():
    bound = bind_forecast(raw(), forecast(value=8.0, upper=13.5))
    main = next(t for t in bound["tanks"] if t["tank_id"] == "main")
    assert main["properties"]["sulfur_mgkg"]["value"] == pytest.approx(13.5)
    assert "допуском" in main["properties"]["sulfur_mgkg"]["note"]


def test_the_bound_value_is_marked_as_derived_not_as_a_scenario_constant():
    bound = bind_forecast(raw(), forecast())
    main = next(t for t in bound["tanks"] if t["tank_id"] == "main")
    assert main["properties"]["sulfur_mgkg"]["source"] == "derived"
    assert parse_scenario(bound).tank("main").inventory.measured is False


def test_a_measurement_outranks_the_chain_model_for_the_current_level():
    bound = bind_forecast(raw(), forecast(upper=13.5))
    main = next(t for t in bound["tanks"] if t["tank_id"] == "main")
    assert main["sulfur_from_chain"] is False
    assert parse_scenario(bound).tank("main").property_value("sulfur_mgkg") == pytest.approx(13.5)


def test_the_original_scenario_is_not_modified():
    before = raw()
    bind_forecast(before, forecast())
    assert before == raw()


def test_an_unavailable_forecast_cannot_be_bound():
    unavailable = {**forecast(available=False), "reason": "Выбранный прогноз недоступен"}
    with pytest.raises(LiveError, match="недоступен"):
        bind_forecast(raw(), unavailable)


def test_binding_to_a_missing_tank_is_refused():
    with pytest.raises(LiveError, match="не описан"):
        bind_forecast(raw(), forecast(), tank_id="ghost")


def test_a_scenario_cannot_claim_both_chain_and_measurement():
    broken = bind_forecast(raw(), forecast())
    for tank in broken["tanks"]:
        if tank["tank_id"] == "main":
            tank["sulfur_from_chain"] = True
    with pytest.raises(ScenarioError, match="одновременно"):
        parse_scenario(broken)


# --- The bound forecast actually reaches the decision ---

def test_a_bound_forecast_changes_the_computed_blend():
    """The scenario chain model must not overwrite a real forecast."""
    def blend_sulfur(upper):
        scenario = parse_scenario(bind_forecast(raw(), forecast(upper=upper)))
        planner = Planner(scenario)
        operation = scenario.current_operation
        recipe = {t.tank_id: float(operation.recipe.get(t.tank_id, 0.0)) for t in scenario.tanks}
        plan = PlanCandidate("hold", (PlanStepSpec(0.0, planner.base_controls(), recipe,
                                                   operation.throughput.value),))
        checks = [c for c in planner.evaluate(plan).gate.checks
                  if c.constraint_id == "quality.sulfur_mgkg" and c.observed is not None]
        return max(c.observed for c in checks)

    low, high = blend_sulfur(6.0), blend_sulfur(14.0)
    assert high > low + 1.0, "прогноз не дошёл до расчёта смеси"


def test_a_high_forecast_makes_the_current_regime_infeasible():
    scenario = parse_scenario(bind_forecast(raw(), forecast(upper=25.0)))
    planner = Planner(scenario)
    operation = scenario.current_operation
    recipe = {t.tank_id: float(operation.recipe.get(t.tank_id, 0.0)) for t in scenario.tanks}
    plan = PlanCandidate("hold", (PlanStepSpec(0.0, planner.base_controls(), recipe,
                                               operation.throughput.value),))
    assert planner.evaluate(plan).feasible is False


def test_crude_quality_still_reaches_the_decision_without_a_bound_forecast():
    """When no measurement is bound, the chain supplies the level, so crude matters."""
    def blend_sulfur(crude_sulfur):
        document = raw()
        document["crude"]["sulfur_wt_pct"]["value"] = crude_sulfur
        scenario = parse_scenario(document)
        planner = Planner(scenario)
        operation = scenario.current_operation
        recipe = {t.tank_id: float(operation.recipe.get(t.tank_id, 0.0)) for t in scenario.tanks}
        plan = PlanCandidate("hold", (PlanStepSpec(0.0, planner.base_controls(), recipe,
                                                   operation.throughput.value),))
        checks = [c for c in planner.evaluate(plan).gate.checks
                  if c.constraint_id == "quality.sulfur_mgkg" and c.observed is not None]
        return max(c.observed for c in checks)

    assert blend_sulfur(2.2) > blend_sulfur(1.35) + 1.0, "качество сырья не дошло до решения"


def test_an_action_still_shifts_the_bound_level():
    """The chain supplies the response ratio even when the level comes from a measurement."""
    scenario = parse_scenario(bind_forecast(raw(), forecast(upper=13.0)))
    planner = Planner(scenario)
    operation = scenario.current_operation
    recipe = {t.tank_id: float(operation.recipe.get(t.tank_id, 0.0)) for t in scenario.tanks}

    def worst(controls):
        plan = PlanCandidate("p", (PlanStepSpec(0.0, {**planner.base_controls(), **controls},
                                                recipe, operation.throughput.value),))
        checks = [c for c in planner.evaluate(plan).gate.checks
                  if c.constraint_id == "quality.sulfur_mgkg" and c.observed is not None]
        return min(c.observed for c in checks)

    assert worst({"ht_reactor_inlet_temp_c": 358.0}) < worst({}), "коррекция не снижает серу"


# --- The state comes from what was available ---

def synthetic():
    times = pd.date_range("2026-01-01", periods=600, freq="10min")
    signals = pd.DataFrame({"avt.T1": np.linspace(100, 120, len(times)),
                            "ht.P3": np.linspace(1, 2, len(times))}, index=times)
    online = pd.DataFrame({"time": times, "value": 6 + np.arange(len(times)) / 1000})
    lab = series_frame([(t.isoformat(), 7.0) for t in times[::72]], "test")
    bundle = {"config": {"horizon_hours": 2, "lab_delay_hours": 4, "history_window_hours": 6,
                         "lab_max_age_hours": 48, "pak_max_age_minutes": 30}}
    return signals, lab, online, bundle


def test_the_state_carries_the_source_ages_and_flags():
    signals, lab, online, bundle = synthetic()
    state = state_at(signals, lab, online, bundle, pd.Timestamp("2026-01-03 00:00"))
    assert state["origin"] == "real_measurements_at_decision_time"
    for key in ("lab_value", "lab_age_hours", "pak_value", "pak_age_minutes",
                "pak_frozen", "telemetry_missing_fraction"):
        assert key in state


def test_an_unavailable_forecast_is_reported_rather_than_guessed():
    signals, lab, online, bundle = synthetic()
    bundle.update(selected="last_lab", fallback="last_lab", radii={"last_lab": 0.2})
    lab_empty = lab.iloc[:0]
    result = forecast_at(signals, lab_empty, online, bundle, pd.Timestamp("2026-01-03 00:00"))
    assert result["available"] is False
    assert result["value"] is None


def test_the_forecast_interval_brackets_its_point_estimate():
    signals, lab, online, bundle = synthetic()
    bundle.update(selected="last_pak", fallback="last_pak", radii={"last_pak": 0.2})
    result = forecast_at(signals, lab, online, bundle, pd.Timestamp("2026-01-03 00:00"))
    assert result["available"] is True
    assert result["lower"] <= result["value"] <= result["upper"]
