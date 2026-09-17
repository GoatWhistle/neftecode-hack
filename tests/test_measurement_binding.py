"""Измерения тегов и отклик по данным попадают в живое решение; без них — сценарий, без числовой уставки."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from neftecode.application.use_cases.get_live_advice import binding_summary
from neftecode.application.use_cases.plan_operation import PlanOperation
from neftecode.evaluation.robustness import RobustnessCheck, response_perturbations
from neftecode.infrastructure.config.scenario import parse_scenario
from neftecode.infrastructure.live.advisor import (LiveError, bind_forecast, bind_measurements,
                                                   load_response_model, measurements_at)

BASELINE = Path("config/scenarios/baseline.json")
DENSITY = {"density_kgm3": 836.1}


def raw():
    return json.loads(BASELINE.read_text())


def forecast(value=6.0, upper=9.0):
    return {"model": "last_pak", "value": value, "lower": 4.0, "upper": upper, "available": True, "reason": "тест"}


def response(**overrides):
    base = {"schema_version": "v1", "tag": "ht.T6", "flow_tag": "ht.F9", "tau": "2026-01-01", "window_months": 12,
            "beta_mgkg_per_c": -0.4332, "ci": [-0.4761, -0.397], "envelope_dt_c": 2.0, "n_rows": 48938,
            "method": "тест", "drift": [], "flow_beta": None, "model_fingerprint": "x",
            "t6_range_c": [342.9, 386.1], "f9_range_tph": [150.3, 256.7], "weak_strong": [-0.217, -0.739]}
    return {**base, **overrides}


def reading(value, at="2026-01-05T08:00:00", age=0.0):
    return {"value": value, "time": at, "age_min": age, "max_age_min": 30.0}


def measured(t6=367.8, f9=206.1, f26=244.1):
    return {"ht.T6": None if t6 is None else reading(t6),
            "ht.F9": None if f9 is None else reading(f9),
            "ht.F26": None if f26 is None else reading(f26)}


def ht(bound):
    return bound["stages"]["hydrotreating"]


# --- уставки ---

def test_measured_temperature_becomes_the_current_setpoint_with_the_research_envelope():
    bound = bind_measurements(raw(), measured(), DENSITY, response(), forecast())
    temp = ht(bound)["controls"]["ht_reactor_inlet_temp_c"]
    assert temp["current"]["value"] == pytest.approx(367.8)
    assert temp["current"]["source"] == "measured"
    assert (temp["min"]["value"], temp["max"]["value"]) == (pytest.approx(365.8), pytest.approx(369.8))
    assert temp["min"]["source"] == "derived"
    assert parse_scenario(bound).tank("main").inventory.measured is False


def test_without_a_temperature_reading_the_setpoint_stays_scenario_and_is_not_advised():
    bound = bind_measurements(raw(), measured(t6=None), DENSITY, response(), forecast())
    temp = ht(bound)["controls"]["ht_reactor_inlet_temp_c"]
    assert temp["current"]["value"] == pytest.approx(348.0)
    assert temp["current"]["source"] == "scenario"
    assert temp["min"]["value"] == temp["max"]["value"] == temp["current"]["value"]
    assert ht(bound)["model"]["provenance"] == "scenario"
    plans, _ = PlanOperation(parse_scenario(bound)).build_plans(budget=60)
    temps = {step.controls.get("ht_reactor_inlet_temp_c") for plan in plans for step in plan.steps}
    assert temps <= {348.0}, "без измерения температура не варьируется"


def test_outside_the_studied_region_the_measurement_is_kept_but_no_numeric_advice_is_given():
    bound = bind_measurements(raw(), measured(t6=296.8, f9=156.0), DENSITY, response(), forecast())
    temp = ht(bound)["controls"]["ht_reactor_inlet_temp_c"]
    assert temp["current"]["source"] == "measured"
    assert temp["min"]["value"] == temp["max"]["value"] == pytest.approx(296.8)
    assert "вне области" in temp["min"]["note"]
    assert ht(bound)["model"]["provenance"] == "scenario"
    assert ht(bound)["model"]["conversion_per_degree"] == pytest.approx(0.085)


def test_feed_flow_is_the_measured_mass_flow_converted_by_density_and_not_varied():
    bound = bind_measurements(raw(), measured(), DENSITY, response(), forecast())
    flow = ht(bound)["controls"]["ht_feed_flow_m3h"]
    assert flow["current"]["value"] == pytest.approx(206.1 * 1000 / 836.1, rel=1e-6)
    assert flow["current"]["source"] == "derived"
    assert flow["min"]["value"] == flow["max"]["value"] == flow["current"]["value"]
    assert flow["actuation"]["measured_tag"] == "ht.F9"


# --- модель отклика ---

def test_the_response_slope_is_linearised_at_the_forecast_value():
    bound = bind_measurements(raw(), measured(), DENSITY, response(), forecast(value=6.0))
    model = ht(bound)["model"]
    assert model["provenance"] == "derived"
    assert model["conversion_per_degree"] == pytest.approx(0.4332 / 6.0)
    assert model["reference_temp_c"] == pytest.approx(367.8)
    assert model["beta_ci"] == [-0.4761, -0.397]
    bound_f = bind_forecast(bound, forecast(value=6.0, upper=9.0))
    plan = PlanOperation(parse_scenario(bound_f))
    idle = plan.inflow_properties(3.0, ())["main"]["sulfur_mgkg"]
    warmer = plan.inflow_properties(3.0, ((0.0, {"ht_reactor_inlet_temp_c": 368.8}),))["main"]["sulfur_mgkg"]
    assert idle == pytest.approx(9.0)
    assert warmer / idle == pytest.approx(np.exp(-0.4332 / 6.0), rel=1e-6)


def test_without_the_response_file_the_model_stays_scenario():
    bound = bind_measurements(raw(), measured(), DENSITY, None, forecast())
    model = ht(bound)["model"]
    assert model["provenance"] == "scenario"
    assert model["conversion_per_degree"] == pytest.approx(0.085)
    temp = ht(bound)["controls"]["ht_reactor_inlet_temp_c"]
    assert temp["min"]["value"] == temp["max"]["value"]
    assert "отклик по данным не загружен" in bound["measurement_binding"]["notes"]


def test_a_broken_response_file_is_an_error_not_a_silent_fallback(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "response_model.json").write_text('{"schema_version": "v1", "tag": "ht.T11"}')
    with pytest.raises(ValueError, match="ht.T6"):
        load_response_model(tmp_path)
    assert load_response_model(tmp_path / "nowhere") is None


def test_the_committed_response_file_is_valid_and_carries_the_studied_region():
    model = load_response_model(Path("."))
    assert model["beta_mgkg_per_c"] < 0
    assert model["t6_range_c"][0] < 367.8 < model["t6_range_c"][1]
    assert model["ci"][0] <= model["beta_mgkg_per_c"] <= model["ci"][1]


# --- приток и окно резервуара ---

def test_the_measured_product_flow_becomes_the_tank_inflow_and_sets_the_refresh_window():
    bound = bind_measurements(raw(), measured(), DENSITY, response(), forecast())
    main = next(t for t in bound["tanks"] if t["tank_id"] == "main")
    assert main["inflow"]["value"] == pytest.approx(244.1 * 836.1 / 1000, rel=1e-6)
    assert main["inflow"]["source"] == "derived"
    assert bound["policy"]["tank_level_window_hours"] == pytest.approx(4000 / (244.1 * 836.1 / 1000), rel=1e-4)


def test_the_refresh_window_is_clamped_to_the_history_range():
    bound = bind_measurements(raw(), measured(f26=1.0), DENSITY, response(), forecast())
    assert bound["policy"]["tank_level_window_hours"] == 72.0
    bound = bind_measurements(raw(), measured(f26=1e6), DENSITY, response(), forecast())
    assert bound["policy"]["tank_level_window_hours"] == 1.0


def test_without_a_flow_reading_the_scenario_inflow_is_kept():
    bound = bind_measurements(raw(), measured(f26=None), DENSITY, response(), forecast())
    main = next(t for t in bound["tanks"] if t["tank_id"] == "main")
    assert main["inflow"] == raw()["tanks"][0]["inflow"]
    assert "ht.F26" in " ".join(bound["measurement_binding"]["notes"])


def test_the_forecast_contribution_over_the_horizon_is_written_as_a_number():
    when = pd.Timestamp("2026-01-05T08:00:00")
    state = {"decision_time": when.isoformat(), "origin": "real_measurements_at_decision_time",
             "quality_history_hours": 72, "pak_expected_per_hour": 6.0,
             "pak_trusted_hourly": [[(when.floor("h") - pd.Timedelta(value=h, unit="h")).isoformat(), 5.0, 6] for h in range(72)],
             "lab_recent": []}
    bound = bind_measurements(raw(), measured(), DENSITY, response(), forecast(upper=9.0))
    bound = bind_forecast(bound, forecast(upper=9.0), state=state)
    main = next(t for t in bound["tanks"] if t["tank_id"] == "main")
    q = 244.1 * 836.1 / 1000
    shift = (9.0 - 5.0) * (1 - np.exp(-q * 3 / 4000))
    assert f"{shift:+.3f}" in main["inflow_sulfur_mgkg"]["note"]


# --- измерения на момент ---

def test_measurements_take_the_last_finite_value_within_the_analyser_age_rule():
    times = pd.date_range("2026-01-05 06:00", periods=13, freq="10min")
    signals = pd.DataFrame({"ht.T6": np.full(13, 367.8), "ht.F9": np.full(13, 206.1), "ht.F26": np.full(13, 244.1)},
                           index=times)
    signals.loc[times[-1], "ht.T6"] = np.nan
    signals.loc[times[-6:], "ht.F9"] = np.nan
    cfg = {"pak_frozen_readings": 4, "pak_period_minutes": 10, "source_rule_method": {"pak_age_periods": 3}}
    out = measurements_at(signals, times[-1], cfg)
    assert out["ht.T6"]["value"] == 367.8 and out["ht.T6"]["age_min"] == 10
    assert out["ht.F9"] is None, "последнее значение старше трёх периодов опроса"
    assert out["ht.F26"]["age_min"] == 0


# --- устойчивость на связанном сценарии ---

def test_robustness_perturbs_the_data_driven_slope_over_the_next_half_year_range():
    bound = bind_measurements(raw(), measured(), DENSITY, response(), forecast(value=6.0))
    specs = response_perturbations(bound)
    assert [round(s["factor"], 4) for s in specs] == [round(-0.217 / -0.4332, 4), round(-0.739 / -0.4332, 4)]
    assert response_perturbations(raw()) == ()


def test_robustness_sees_the_bound_reference_temperature():
    bound = bind_forecast(bind_measurements(raw(), measured(), DENSITY, response(), forecast()), forecast())
    check = RobustnessCheck(parse_scenario(bound), bound, scenario_parser=parse_scenario)
    assert check.raw["stages"]["hydrotreating"]["model"]["reference_temp_c"] == pytest.approx(367.8)


def test_binding_summary_reports_sources_of_every_bound_quantity():
    bound = bind_forecast(bind_measurements(raw(), measured(), DENSITY, response(), forecast()), forecast())
    summary = binding_summary(bound)
    assert summary["controls"]["ht_reactor_inlet_temp_c"]["current"]["source"] == "measured"
    assert summary["controls"]["ht_feed_flow_m3h"]["current"]["source"] == "derived"
    assert summary["response_model"]["provenance"] == "derived"
    assert summary["tank_inflow"]["source"] == "derived"
    assert binding_summary({"stages": {}, "tanks": []}) is None


def test_binding_requires_a_positive_density():
    with pytest.raises(LiveError):
        bind_measurements(raw(), measured(), {"density_kgm3": 0.0}, response(), forecast())
