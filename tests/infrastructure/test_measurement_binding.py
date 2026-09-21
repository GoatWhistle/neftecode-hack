import json
import math
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
from neftecode.infrastructure.response.estimate import response_at

BASELINE = Path("config/scenarios/baseline.json")
DENSITY = {"density_kgm3": 836.1}


def raw():
    return json.loads(BASELINE.read_text(encoding="utf-8"))


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



def test_measured_temperature_becomes_the_current_setpoint_with_the_research_envelope():
    bound = bind_measurements(raw(), measured(), DENSITY, response(), forecast())
    assert set(bound["policy"]["disabled_control_moves"]) >= {
        "crude_feed_rate_tph", "avt_furnace_outlet_temp_c"
    }
    assert "промежуточные ёмкости" in bound["policy"]["disabled_control_moves_note"]
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


def test_a_measured_t6_without_a_measured_f9_does_not_open_the_setpoint_range():
    # Дефект #3 (пул I2): T6 измерен и внутри диапазона исследования, но F9 не измерен —
    # ход T6 не должен предлагаться, потому что область применимости модели отклика
    # зависит от F9, а сценарный F9 не подтверждает применимость.
    bound = bind_measurements(raw(), measured(t6=367.8, f9=None), DENSITY, response(), forecast())
    temp = ht(bound)["controls"]["ht_reactor_inlet_temp_c"]
    assert temp["current"]["source"] == "measured"
    assert temp["current"]["value"] == pytest.approx(367.8)
    assert temp["min"]["value"] == temp["max"]["value"] == temp["current"]["value"] == pytest.approx(367.8)
    assert temp["min"]["source"] == "scenario"
    assert "F9 не измерен" in temp["min"]["note"]
    assert "ход T6 не разрешён: ht.F9 не измерен" in bound["measurement_binding"]["notes"]
    assert ht(bound)["model"]["provenance"] == "scenario"
    plans, _ = PlanOperation(parse_scenario(bound)).build_plans(budget=60)
    temps = {step.controls.get("ht_reactor_inlet_temp_c") for plan in plans for step in plan.steps}
    assert temps <= {367.8}, "без измеренного F9 T6 не варьируется, несмотря на измеренный T6 в области"


def test_outside_the_studied_region_the_measurement_is_kept_but_no_numeric_advice_is_given():
    bound = bind_measurements(raw(), measured(t6=296.8, f9=156.0), DENSITY, response(), forecast())
    temp = ht(bound)["controls"]["ht_reactor_inlet_temp_c"]
    assert temp["current"]["source"] == "measured"
    assert temp["min"]["value"] == temp["max"]["value"] == pytest.approx(296.8)
    assert "вне области" in temp["min"]["note"]
    assert ht(bound)["model"]["provenance"] == "scenario"
    assert ht(bound)["model"]["conversion_per_degree"] == pytest.approx(0.085)


def test_outside_the_studied_region_the_advice_carries_an_explicit_warning():
    bound = bind_measurements(raw(), measured(t6=296.8, f9=156.0), DENSITY, response(), forecast())
    warnings = bound["measurement_binding"]["warnings"]
    assert len(warnings) == 1 and "ht.T6 = 296.8" in warnings[0] and "ht.F9" not in warnings[0]
    assert bind_measurements(raw(), measured(), DENSITY, response(), forecast())["measurement_binding"]["warnings"] == []


def test_feed_flow_is_the_measured_mass_flow_converted_by_density_and_not_varied():
    bound = bind_measurements(raw(), measured(), DENSITY, response(), forecast())
    flow = ht(bound)["controls"]["ht_feed_flow_m3h"]
    assert flow["current"]["value"] == pytest.approx(206.1 * 1000 / 836.1, rel=1e-6)
    assert flow["current"]["source"] == "derived"
    assert flow["min"]["value"] == flow["max"]["value"] == flow["current"]["value"]
    assert flow["actuation"]["measured_tag"] == "ht.F9"



def test_the_response_slope_is_linearised_at_the_inflow_sulfur_the_plan_scales():
    bound = bind_measurements(raw(), measured(), DENSITY, response(), forecast(value=6.0, upper=9.0))
    model = ht(bound)["model"]
    assert model["provenance"] == "derived"
    assert model["conversion_per_degree"] == pytest.approx(0.4332 / 9.0)
    assert model["linearization_sulfur_mgkg"] == pytest.approx(9.0)
    assert model["reference_temp_c"] == pytest.approx(367.8)
    assert model["beta_ci"] == [-0.4761, -0.397]
    bound_f = bind_forecast(bound, forecast(value=6.0, upper=9.0))
    plan = PlanOperation(parse_scenario(bound_f))
    idle = plan.inflow_properties(3.0, ())["main"]["sulfur_mgkg"]
    warmer = plan.inflow_properties(3.0, ((0.0, {"ht_reactor_inlet_temp_c": 367.9}),))["main"]["sulfur_mgkg"]
    assert idle == pytest.approx(9.0)
    assert (warmer - idle) / 0.1 == pytest.approx(-0.4332, rel=1e-2)


def test_the_response_is_relinearised_when_a_frozen_analyser_raises_the_inflow():
    state = {"origin": "real_measurements_at_decision_time", "decision_time": "2026-01-05T08:00:00",
             "pak_frozen": True, "pak_last_trusted_value": 13.0, "pak_last_trusted_time": "2026-01-05T07:00:00",
             "lab_recent": [], "quality_history_hours": 72, "pak_expected_per_hour": 6.0,
             "pak_trusted_hourly": [[f"2026-01-05T{h:02d}:00:00", 5.0, 6] for h in range(8)]}
    bound = bind_measurements(raw(), measured(), DENSITY, response(), forecast(value=6.0, upper=9.0))
    bound["policy"]["tank_level_window_hours"] = 6.0
    bound = bind_forecast(bound, forecast(value=6.0, upper=9.0), state=state)
    model = ht(bound)["model"]
    assert bound["tanks"][0]["inflow_sulfur_mgkg"]["value"] == pytest.approx(13.0)
    assert model["conversion_per_degree"] == pytest.approx(0.4332 / 13.0)
    assert "зависшего ПАК" in model["note"]


def test_without_the_response_file_the_model_stays_scenario():
    bound = bind_measurements(raw(), measured(), DENSITY, None, forecast())
    model = ht(bound)["model"]
    assert model["provenance"] == "scenario"
    assert model["conversion_per_degree"] == pytest.approx(0.085)
    temp = ht(bound)["controls"]["ht_reactor_inlet_temp_c"]
    assert temp["min"]["value"] == temp["max"]["value"]
    assert "отклик по данным не загружен" in bound["measurement_binding"]["notes"]


def test_a_broken_response_file_is_an_error_not_a_silent_fallback(tmp_path):
    (tmp_path / "artifacts").mkdir()
    (tmp_path / "artifacts" / "response_model.json").write_text('{"schema_version": "v1", "tag": "ht.T11"}', encoding="utf-8")
    with pytest.raises(ValueError, match="ht.T6"):
        load_response_model(tmp_path)
    with pytest.raises(ValueError, match="ht.T6"):
        load_response_model(tmp_path / "nowhere", out=tmp_path / "artifacts")
    assert load_response_model(tmp_path / "nowhere") is None


def test_the_declared_policy_file_carries_no_hand_written_estimate():
    declared = json.loads(Path("config/response_model.json").read_text(encoding="utf-8"))
    assert declared["tag"] == "ht.T6" and declared["envelope_dt_c"] == 2.0
    assert declared["response_onset_hours"] == 2.0 and declared["horizon_response_share"] == 0.66
    assert declared["observed_plateau_window_hours"] == [3.0, 8.0]
    assert "beta_mgkg_per_c" not in declared and "weak_strong" not in declared, "β теперь оценивает train"


def test_the_trained_response_artifact_reproduces_the_study_at_tau_2026():
    artifact = Path("artifacts/response_model.json")
    if not artifact.exists():
        pytest.skip("artifacts/response_model.json появляется после train")
    model = load_response_model(Path("."))
    assert model["primary"] == "train_end" and pd.Timestamp(model["tau"]) == pd.Timestamp("2025-01-01")
    assert model["beta_mgkg_per_c"] < 0 and model["ci"][0] <= model["beta_mgkg_per_c"] <= model["ci"][1]
    at_2026 = response_at(model, "2026-01-05T08:00:00")
    assert pd.Timestamp(at_2026["tau"]) == pd.Timestamp("2026-01-01")
    assert at_2026["beta_mgkg_per_c"] == pytest.approx(-0.4226, abs=5e-4)
    assert at_2026["ci"] == pytest.approx([-0.4767, -0.389], abs=5e-4)
    assert at_2026["weak_strong"] == pytest.approx([-0.211, -0.721], abs=2e-3)
    assert at_2026["t6_range_c"] == pytest.approx([342.9, 386.1], abs=0.15)
    assert at_2026["f9_range_tph"] == pytest.approx([149.8, 256.7], abs=0.15)
    assert at_2026["feed_floor_tph"] == pytest.approx(133.457, abs=5e-4)
    assert pd.Timestamp(at_2026["feed_floor_until"]) == pd.Timestamp("2025-12-31T18:00:00")
    assert model["horizon_response_share"] == 0.66 and model["response_onset_hours"] == 2.0


def test_the_live_binding_takes_the_estimate_made_strictly_before_the_moment():
    early = {**response(), "tau": "2025-07-01", "beta_mgkg_per_c": -0.481, "ci": [-0.508, -0.45],
             "weak_strong": [-0.24, -0.82], "n_rows": 1}
    late = {**response(), "tau": "2026-01-01", "n_rows": 2}
    rolling = {**response(), "estimates": [{k: e[k] for k in ("tau", "beta_mgkg_per_c", "ci", "n_rows", "weak_strong",
                                                             "t6_range_c", "f9_range_tph")} for e in (early, late)]}
    jan = ht(bind_measurements(raw(), measured(), DENSITY, rolling, forecast(), at="2026-01-05T08:00:00"))["model"]
    assert (jan["beta_mgkg_per_c"], jan["response_tau"], jan["response_rows"]) == (-0.4332, "2026-01-01", 2)
    dec = ht(bind_measurements(raw(), measured(), DENSITY, rolling, forecast(), at="2025-12-31T23:00:00"))["model"]
    assert (dec["beta_mgkg_per_c"], dec["response_tau"]) == (-0.481, "2025-07-01")
    before = bind_measurements(raw(), measured(), DENSITY, rolling, forecast(), at="2025-03-01T00:00:00")
    assert ht(before)["model"]["provenance"] == "scenario"
    assert any("сделанной до 2025-03-01" in note for note in before["measurement_binding"]["notes"])
    with pytest.raises(LiveError, match="момента решения"):
        bind_measurements(raw(), measured(), DENSITY, rolling, forecast())
    assert response_at(response(), "2020-01-01") == response(), "файл без estimates — как прежде"



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



def test_interval_coverage_reads_target_and_test_from_the_artifacts(tmp_path):
    from neftecode.infrastructure.live.advisor import interval_coverage
    bundle = {"config": {"interval_coverage": 0.9}, "selected": "last_pak"}
    assert interval_coverage(tmp_path, bundle) == {"coverage_target": 0.9}
    (tmp_path / "metrics.json").write_text(json.dumps({"models": {"last_pak": {"test": {"interval_coverage": 0.867}}}}), encoding="utf-8")
    assert interval_coverage(tmp_path, bundle) == {"coverage_target": 0.9, "coverage_test": 0.867}
    (tmp_path / "metrics.json").write_text(json.dumps({"models": {
        "last_pak": {"test": {"interval_coverage": 0.867}},
        "catboost_no_pak": {"test": {"interval_coverage": 0.819}},
    }}), encoding="utf-8")
    assert interval_coverage(tmp_path, bundle, "catboost_no_pak") == {
        "coverage_target": 0.9, "coverage_test": 0.819,
    }


def test_the_inflow_note_states_the_actual_coverage_when_known():
    fc = {**forecast(upper=9.0), "coverage_target": 0.9, "coverage_test": 0.867}
    bound = bind_forecast(raw(), fc)
    note = next(t for t in bound["tanks"] if t["tank_id"] == "main")["inflow_sulfur_mgkg"]["note"]
    assert "покрытие 90%" in note and "86.7%" in note
    from neftecode.application.contracts import LiveForecast
    live = LiveForecast.from_dict({**fc, "coverage_test_2026": 0.867})
    assert live.to_dict()["coverage_test"] == 0.867



def test_the_bound_lag_is_the_research_onset_and_the_scenario_files_keep_their_own():
    bound = bind_measurements(raw(), measured(), DENSITY, response(response_onset_hours=2.0, horizon_response_share=0.66),
                              forecast())
    lag = ht(bound)["response_lag_hours"]
    assert (lag["value"], lag["source"]) == (2.0, "derived")
    assert "0,5–2 ч" in lag["note"] and "3–8 ч" in lag["note"]
    assert ht(bound)["model"]["horizon_response_share"] == pytest.approx(0.66)
    assert ht(bound)["model"]["horizon_response_until_hours"] == pytest.approx(3.0)
    assert ht(raw())["response_lag_hours"]["value"] == 2.0, "сценарный файл не меняется"
    assert ht(bind_measurements(raw(), measured(), DENSITY, None, forecast()))["response_lag_hours"]["value"] == 2.0
    outside = bind_measurements(raw(), measured(t6=296.8), DENSITY, response(), forecast())
    assert ht(outside)["response_lag_hours"]["source"] == "scenario"


def test_without_the_declared_fields_the_onset_is_two_hours_and_the_full_move_counts():
    bound = bind_measurements(raw(), measured(), DENSITY, response(), forecast())
    assert ht(bound)["response_lag_hours"]["value"] == 2.0
    assert ht(bound)["model"]["horizon_response_share"] == 1.0


@pytest.mark.parametrize("field, value", [("response_onset_hours", 4.0), ("response_onset_hours", -1),
                                          ("horizon_response_share", 0.0), ("horizon_response_share", 1.5)])
def test_declared_lag_fields_are_validated(field, value):
    from neftecode.infrastructure.live.advisor import validate_response_model
    with pytest.raises(ValueError, match=field):
        validate_response_model(response(**{field: value}))


def test_no_effect_before_the_onset_and_only_the_declared_share_within_the_horizon():
    bound = bind_forecast(bind_measurements(raw(), measured(), DENSITY,
                                            response(response_onset_hours=2.0, horizon_response_share=0.66),
                                            forecast(value=6.0, upper=9.0)), forecast(value=6.0, upper=9.0))
    plan = PlanOperation(parse_scenario(bound))
    move = ((0.0, {"ht_reactor_inlet_temp_c": 368.8}),)
    idle = {t: plan.inflow_properties(t, ())["main"]["sulfur_mgkg"] for t in (1.5, 2.0, 3.0, 3.5)}
    warm = {t: plan.inflow_properties(t, move)["main"]["sulfur_mgkg"] for t in (1.5, 2.0, 3.0, 3.5)}
    assert warm[1.5] == pytest.approx(idle[1.5]), "до 2 ч эффекта нет"
    k = 0.4332 / 9.0
    assert warm[2.0] == pytest.approx(9.0 * math.exp(-k * 0.66)), "на 2 ч начинается частичный эффект"
    assert warm[3.0] == pytest.approx(9.0 * math.exp(-k * 0.66)), "на 3 ч — 66 % хода"
    assert warm[3.5] == pytest.approx(9.0 * math.exp(-k * 1.0)), "за горизонтом — весь ход"
    chain = plan.chain.hydrotreating
    assert chain.to_dict()["horizon_response_share"] == pytest.approx(0.66)
    assert chain.effective_controls(3.0, {"ht_reactor_inlet_temp_c": 367.8}, move)["ht_reactor_inlet_temp_c"] \
        == pytest.approx(367.8 + 0.66)


def test_the_explanation_names_the_derived_delay_and_the_share():
    from neftecode.application.services.explain import explain
    from neftecode.application.use_cases.make_decision import MakeDecision
    bound = bind_forecast(bind_measurements(raw(), measured(), DENSITY,
                                            response(response_onset_hours=2.0, horizon_response_share=0.66),
                                            forecast()), forecast())
    scenario = parse_scenario(bound)
    decision = MakeDecision(scenario).decide(budget=100, raw_scenario=bound)
    delay = next(s for s in explain(decision, scenario)["statements"] if s["topic"] == "delay")
    assert delay["value"] == 2.0 and "66%" in delay["text"]
    assert delay["evidence"][0]["kind"] == "model"
