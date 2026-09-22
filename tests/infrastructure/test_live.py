import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from neftecode.infrastructure.data.data import series_frame
from neftecode.infrastructure.live.advisor import LiveError, bind_forecast, forecast_at, state_at
from neftecode.application.use_cases.plan_operation import PlanOperation, PlanCandidate, PlanStep
from neftecode.infrastructure.config.scenario import ScenarioError, load_scenario, parse_scenario

BASELINE = Path("config/scenarios/baseline.json")


def raw():
    return json.loads(BASELINE.read_text(encoding="utf-8"))


def forecast(value=12.0, upper=14.0, model="last_pak", available=True):
    return {"model": model, "value": value, "lower": value - 2, "upper": upper,
            "available": available, "reason": "тест"}



def test_the_upper_bound_feeds_the_inflow_not_the_stored_product():
    bound = bind_forecast(raw(), forecast(value=8.0, upper=13.5))
    main = next(t for t in bound["tanks"] if t["tank_id"] == "main")
    assert main["inflow_sulfur_mgkg"]["value"] == pytest.approx(13.5)
    assert "точечная оценка" in main["inflow_sulfur_mgkg"]["note"]
    assert main["properties"]["sulfur_mgkg"] == raw()["tanks"][0]["properties"]["sulfur_mgkg"]


def test_the_bound_value_is_marked_as_derived_not_as_a_scenario_constant():
    bound = bind_forecast(raw(), forecast())
    main = next(t for t in bound["tanks"] if t["tank_id"] == "main")
    assert main["inflow_sulfur_mgkg"]["source"] == "derived"
    assert parse_scenario(bound).tank("main").inventory.measured is False


def test_a_measurement_outranks_the_chain_model_for_the_inflow():
    bound = bind_forecast(raw(), forecast(upper=13.5))
    main = next(t for t in bound["tanks"] if t["tank_id"] == "main")
    assert main["sulfur_from_chain"] is False
    assert parse_scenario(bound).tank("main").inflow_sulfur.value == pytest.approx(13.5)


def measured_state(hourly_mean, hours=72, decision_time="2026-03-01T12:00:00", per_hour=6, lab=()):
    when = pd.Timestamp(decision_time)
    return {"decision_time": decision_time, "origin": "real_measurements_at_decision_time",
            "quality_history_hours": 72, "pak_expected_per_hour": float(per_hour),
            "pak_trusted_hourly": [[(when.floor("h") - pd.Timedelta(value=h, unit="h")).isoformat(),
                                    float(hourly_mean), per_hour] for h in range(hours)],
            "lab_recent": [list(item) for item in lab]}


def test_stored_sulfur_is_the_mean_of_trusted_readings_over_the_refresh_window():
    bound = bind_forecast(raw(), forecast(upper=13.5), state=measured_state(7.25))
    main = parse_scenario(bound).tank("main")
    assert main.property_value("sulfur_mgkg") == pytest.approx(7.25)
    assert main.properties["sulfur_mgkg"].source == "derived"
    assert main.inflow_sulfur.value == pytest.approx(13.5)


def test_thin_analyser_history_falls_back_to_the_laboratory():
    state = measured_state(9.0, hours=5, lab=[("2026-03-01T10:00:00", 6.0), ("2026-02-28T20:00:00", 8.0)])
    level = parse_scenario(bind_forecast(raw(), forecast(), state=state)).tank("main")
    assert level.property_value("sulfur_mgkg") == pytest.approx(7.0)
    assert "ЛИМС" in level.properties["sulfur_mgkg"].note


def test_without_enough_history_no_stored_level_is_invented():
    with pytest.raises(LiveError, match="не оценивается"):
        bind_forecast(raw(), forecast(), state=measured_state(9.0, hours=5))


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



def test_a_bound_forecast_changes_the_filling_batch_passport_forecast():
    def passport_sulfur(upper):
        scenario = parse_scenario(bind_forecast(raw(), forecast(value=upper - 2, upper=upper)))
        planner = PlanOperation(scenario)
        operation = scenario.current_operation
        recipe = {t.tank_id: float(operation.recipe.get(t.tank_id, 0.0)) for t in scenario.tanks}
        plan = PlanCandidate("hold", (PlanStep(0.0, planner.base_controls(), recipe,
                                                   operation.throughput.value),))
        checks = [c for c in planner.evaluate(plan).gate.checks
                  if c.constraint_id.endswith("passport_forecast.sulfur_mgkg")
                  and c.observed is not None]
        return max(c.observed for c in checks)

    low, high = passport_sulfur(6.0), passport_sulfur(14.0)
    assert high > low + 0.2, "прогноз не дошёл до паспорта наливаемой партии"


def test_a_high_forecast_into_a_tank_near_the_limit_makes_the_regime_infeasible():
    scenario = parse_scenario(bind_forecast(raw(), forecast(upper=25.0), state=measured_state(10.5)))
    planner = PlanOperation(scenario)
    operation = scenario.current_operation
    recipe = {t.tank_id: float(operation.recipe.get(t.tank_id, 0.0)) for t in scenario.tanks}
    plan = PlanCandidate("hold", (PlanStep(0.0, planner.base_controls(), recipe,
                                               operation.throughput.value),))
    assert planner.evaluate(plan).feasible is False


def test_crude_quality_still_reaches_the_filling_batch_without_a_bound_forecast():
    def passport_sulfur(crude_sulfur):
        document = raw()
        document["crude"]["sulfur_wt_pct"]["value"] = crude_sulfur
        scenario = parse_scenario(document)
        planner = PlanOperation(scenario)
        operation = scenario.current_operation
        recipe = {t.tank_id: float(operation.recipe.get(t.tank_id, 0.0)) for t in scenario.tanks}
        plan = PlanCandidate("hold", (PlanStep(0.0, planner.base_controls(), recipe,
                                                   operation.throughput.value),))
        checks = [c for c in planner.evaluate(plan).gate.checks
                  if c.constraint_id.endswith("passport_forecast.sulfur_mgkg")
                  and c.observed is not None]
        return max(c.observed for c in checks)

    effect = passport_sulfur(2.2) - passport_sulfur(1.35)
    assert effect > 0.0, "качество притока не дошло до паспорта наливаемой партии"


def test_an_action_still_shifts_the_filling_batch_passport_forecast():
    scenario = parse_scenario(bind_forecast(raw(), forecast(upper=13.0)))
    planner = PlanOperation(scenario)
    operation = scenario.current_operation
    recipe = {t.tank_id: float(operation.recipe.get(t.tank_id, 0.0)) for t in scenario.tanks}

    def worst(controls):
        plan = PlanCandidate("p", (PlanStep(0.0, {**planner.base_controls(), **controls},
                                                recipe, operation.throughput.value),))
        checks = [c for c in planner.evaluate(plan).gate.checks
                  if c.constraint_id.endswith("passport_forecast.sulfur_mgkg")
                  and c.observed is not None]
        return max(checks, key=lambda c: c.time_hours).observed

    assert worst({"ht_reactor_inlet_temp_c": 358.0}) < worst({}), "коррекция не снижает серу"



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


def test_future_lab_result_cannot_change_bias_corrected_live_forecast_or_bounds():
    signals, lab, online, bundle = synthetic()
    at = pd.Timestamp("2026-01-04 00:00").as_unit("ns")
    bundle["config"]["forecast_selection"] = json.loads(
        Path("config/experiment.json").read_text(encoding="utf-8")
    )["forecast_selection"]
    bundle.update(selected="last_pak_bc", fallback="last_pak_bc", radii={"last_pak_bc": 0.2})
    before = forecast_at(signals, lab.loc[lab.time <= at], online, bundle, at)
    future = pd.DataFrame({"time": [pd.Timestamp(at.to_datetime64() + np.timedelta64(1, "h"))], "value": [999.0]})
    after = forecast_at(signals, pd.concat([lab, future], ignore_index=True), online, bundle, at)
    assert before == after
    assert before["model"] == "last_pak_bc"
    assert "20 последних доступных пар" in before["reason"]



def test_an_unavailable_chain_level_becomes_unknown_not_the_reference_constant():
    from neftecode.application.use_cases.plan_operation import PlanOperation
    from neftecode.domain.production.process import StreamState

    scenario = load_scenario(BASELINE)
    planner = PlanOperation(scenario)
    assert scenario.tank("main").sulfur_from_chain is True
    original = planner.chain.run_at

    def unavailable(time_hours, pending=(), controls=None):
        if time_hours == 0.0 and not pending:
            return StreamState(100.0, None, None, 865.0, "out_of_region", ("вне области",))
        return original(time_hours, pending, controls)

    planner.chain.run_at = unavailable
    assert planner._main_sulfur() is None, "заглушка подменила неизвестный уровень"


def test_a_plan_is_blocked_when_the_filling_batch_forecast_is_unavailable():
    from neftecode.application.use_cases.plan_operation import PlanOperation
    from neftecode.domain.production.process import StreamState

    scenario = load_scenario(BASELINE)
    planner = PlanOperation(scenario)
    original = planner.chain.run_at

    def unavailable(time_hours, pending=(), controls=None):
        if time_hours == 0.0 and not pending:
            return StreamState(100.0, None, None, 865.0, "out_of_region", ("вне области",))
        return original(time_hours, pending, controls)

    planner.chain.run_at = unavailable
    operation = scenario.current_operation
    recipe = {t.tank_id: float(operation.recipe.get(t.tank_id, 0.0)) for t in scenario.tanks}
    plan = PlanCandidate("hold", (PlanStep(0.0, planner.base_controls(), recipe,
                                               operation.throughput.value),))
    evaluation = planner.evaluate(plan)
    assert evaluation.feasible is False
    assert any(c.constraint_id.endswith("passport_forecast.sulfur_mgkg")
               for c in evaluation.gate.unknown_requirements())


def test_live_refuses_bad_data_before_calling_a_forecast(monkeypatch):
    from neftecode.infrastructure.live.advisor import LiveAdviceAdapter

    state = {"decision_time": "2026-01-05T08:00:00", "lab_value": None,
             "lab_usable": False, "pak_value": None, "pak_usable": False,
             "telemetry_missing_fraction": 1.0}
    monkeypatch.setattr("neftecode.infrastructure.live.providers.state_at", lambda *args: state)

    def forbidden(*args, **kwargs):
        raise AssertionError("forecast executed on rejected inputs")

    monkeypatch.setattr("neftecode.infrastructure.live.providers.forecast_at", forbidden)
    advisor = LiveAdviceAdapter(None, None, None,
                          {"config": {"calibration_end": "2026-01-01"}}, raw())
    result = advisor.advise("2026-01-05T08:00:00")
    assert result["decision"]["status"] == "refuse"
    assert result["forecast"]["available"] is False
    assert result["forecast"]["model"] is None


def test_frozen_pak_selects_the_separate_fallback_forecast(monkeypatch):
    from neftecode.infrastructure.live.advisor import LiveAdviceAdapter

    state = {"decision_time": "2026-01-05T08:00:00", "lab_value": 8.0,
             "lab_age_hours": 5.0, "lab_usable": True, "pak_value": 8.4,
             "pak_age_minutes": 10.0, "pak_usable": True, "pak_frozen": True,
             "pak_conflict": False, "telemetry_missing_fraction": 0.0}
    monkeypatch.setattr("neftecode.infrastructure.live.providers.state_at", lambda *args: state)
    called = []

    def forecast(*args, fallback=False, **kwargs):
        called.append(fallback)
        return {"model": "fallback", "value": 8.0, "lower": 7.0, "upper": 9.0,
                "available": True, "reason": "test"}

    monkeypatch.setattr("neftecode.infrastructure.live.providers.forecast_at", forecast)
    advisor = LiveAdviceAdapter(None, None, None,
                                {"config": {"calibration_end": "2026-01-01"}}, raw())
    result = advisor.advise("2026-01-05T08:00:00")
    assert called == [True]
    assert result["forecast"]["model"] == "fallback"
    assert result["decision"]["status"] in ("hold", "recommend_scenario")


def test_invalid_forecast_binding_returns_structured_local_refusal(monkeypatch):
    from neftecode.infrastructure.live.advisor import LiveAdviceAdapter

    state = {'decision_time': '2026-01-05T08:00:00', 'lab_value': 8.0,
             'lab_age_hours': 5.0, 'lab_usable': True, 'pak_value': 8.4,
             'pak_age_minutes': 10.0, 'pak_usable': True, 'pak_frozen': False,
             'pak_conflict': False, 'telemetry_missing_fraction': 0.0}
    monkeypatch.setattr('neftecode.infrastructure.live.providers.state_at', lambda *args: state)
    monkeypatch.setattr('neftecode.infrastructure.live.providers.forecast_at',
        lambda *args, **kwargs: {'model': 'test', 'value': 8.0, 'lower': 7.0,
                                 'upper': 6.0, 'available': True, 'reason': 'test'})
    result = LiveAdviceAdapter(None, None, None,
        {'config': {'calibration_end': '2026-01-01'}}, raw()).advise(state['decision_time'])
    assert result['decision'] is None
    assert result['explanation'] is None
    assert 'интервал' in result['error']
    assert 'не удалось связать' in result['note']



def history_case():
    from neftecode.infrastructure.data.data import recent_quality_history
    times = pd.date_range("2026-03-01 00:00", "2026-03-03 12:00", freq="10min")
    values = 7.0 + (np.arange(len(times)) % 5) * 0.1
    values[-15:] = 18.45
    online = pd.DataFrame({"time": times, "value": values})
    lab = series_frame([("2026-03-03 09:00", 9.5), ("2026-03-03 11:00", 12.0)], "test")
    cfg = {"horizon_hours": 2, "lab_delay_hours": 4, "history_window_hours": 6}
    return recent_quality_history(lab, online, pd.Timestamp("2026-03-03 12:00"), cfg)


def test_a_flat_analyser_run_is_not_trusted_history():
    history = history_case()
    means = [mean for _, mean, _ in history["pak_trusted_hourly"]]
    assert max(means) < 8.0, "показания зависшего прибора попали в доверенную историю"
    assert history["pak_expected_per_hour"] == pytest.approx(6.0)


def test_laboratory_history_respects_the_publication_delay():
    history = history_case()
    assert [value for _, value in history["lab_recent"]] == [], "проба 09:00 доступна только в 13:00"



def frozen_state(last=13.25, last_at="2026-03-01T10:00:00", lab=()):
    state = measured_state(8.0, lab=lab)
    state.update({"pak_frozen": True, "pak_last_trusted_value": last, "pak_last_trusted_time": last_at})
    return state


def test_a_frozen_analyser_keeps_the_last_trusted_reading_as_the_inflow_floor():
    bound = bind_forecast(raw(), forecast(value=6.5, upper=8.9, model="catboost_no_pak"), state=frozen_state())
    inflow = parse_scenario(bound).tank("main").inflow_sulfur
    assert inflow.value == pytest.approx(13.25)
    assert "завис" in inflow.note


def test_a_later_laboratory_result_replaces_the_held_reading():
    lab = [("2026-03-01T11:00:00", 7.1)]
    bound = bind_forecast(raw(), forecast(value=6.5, upper=8.9), state=frozen_state(lab=lab))
    assert parse_scenario(bound).tank("main").inflow_sulfur.value == pytest.approx(8.9)


def test_an_old_trusted_reading_is_not_held_forever():
    state = frozen_state(last_at="2026-02-20T10:00:00")
    bound = bind_forecast(raw(), forecast(value=6.5, upper=8.9), state=state)
    assert parse_scenario(bound).tank("main").inflow_sulfur.value == pytest.approx(8.9)


def test_the_hold_only_applies_while_the_analyser_is_frozen():
    state = dict(frozen_state(), pak_frozen=False)
    bound = bind_forecast(raw(), forecast(value=6.5, upper=8.9), state=state)
    assert parse_scenario(bound).tank("main").inflow_sulfur.value == pytest.approx(8.9)


def test_history_reports_the_reading_before_the_flat_run():
    history = history_case()
    assert history["pak_last_trusted_value"] < 8.0
    assert history["pak_last_trusted_time"] < "2026-03-03T10:00:00"
