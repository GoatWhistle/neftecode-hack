import json

import pytest

from neftecode.domain.shared.primitives import (CONFIRMED, ContractError, FAIL, HOLD, PASS,
                                 REFUSE, RECOMMEND_SCENARIO, UNKNOWN)
from neftecode.domain.monitoring.entities import Observation, PlantState, ForecastValue
from neftecode.domain.production.state import TankState
from neftecode.domain.shared.actions import PendingAction
from neftecode.domain.advisory.entities import (Decision, GateResult, PlanStep, ActionPlan,
                                 CheckResult, TrajectoryEstimate, TrajectoryPoint)


def observation(**kw):
    base = {"tag_id": "lab.sulfur", "source": "ЛИМС", "value": 8.0, "unit": "мг/кг",
            "measured_at": "2026-01-05T04:00:00", "available_at": "2026-01-05T08:00:00"}
    return Observation(**{**base, **kw})


def tank(tank_id="main", **kw):
    base = {"available": True, "inventory_t": 1000.0,
            "properties": {"sulfur_mgkg": 8.0, "t95_c": 350.0, "cetane_number": 51.0}}
    return TankState(tank_id, **{**base, **kw})


def plan(plan_id="p1", steps=None):
    return ActionPlan(plan_id, tuple(steps or [PlanStep(0.0, recipe={"main": 1.0}, throughput_tph=100.0)]))


def trajectory(plan_id="p1"):
    return TrajectoryEstimate(plan_id, (TrajectoryPoint(0.0, {"sulfur_mgkg": 8.0, "t95_c": 350.0,
                                                              "cetane_number": 51.0}, {"main": 1000.0}),))



def test_late_sample_is_invisible_before_it_was_available():
    o = observation()
    assert o.visible_at("2026-01-05T07:59:00") is False
    assert o.visible_at("2026-01-05T08:00:00") is True
    assert o.age_hours("2026-01-05T08:00:00") == 4.0


def test_availability_before_measurement_is_rejected():
    with pytest.raises(ContractError, match="раньше измерения"):
        observation(available_at="2026-01-05T03:00:00")


def test_nan_observation_becomes_unknown_not_zero():
    assert observation(value=float("nan")).value is None
    assert observation(value=float("inf")).value is None
    assert observation(value=0.0).value == 0.0


def test_unusable_observation_is_not_usable_even_with_a_value():
    assert observation(validity="unusable").usable is False
    assert observation(validity="suspect").usable is False
    assert observation().usable is True


def test_observation_round_trip_keeps_status_and_times():
    o = observation(validity="suspect", issues=("зависание",))
    back = Observation.from_dict(json.loads(json.dumps(o.to_dict())))
    assert back == o
    assert back.issues == ("зависание",)



def test_plant_state_rejects_observation_from_the_future():
    with pytest.raises(ContractError, match="утечка из будущего"):
        PlantState("2026-01-05T06:00:00", observations=(observation(),))


def test_plant_state_accepts_observation_once_available():
    state = PlantState("2026-01-05T08:00:00", observations=(observation(),))
    assert len(state.observations) == 1


def test_recipe_not_summing_to_one_is_rejected():
    with pytest.raises(ContractError, match="доли дают"):
        PlantState("2026-01-05T08:00:00", current_recipe={"main": 0.8, "reserve": 0.1})


def test_plant_state_round_trip_preserves_unknown_throughput():
    state = PlantState("2026-01-05T08:00:00", tanks=(tank(),), current_throughput_tph=None)
    back = PlantState.from_dict(json.loads(json.dumps(state.to_dict())))
    assert back.current_throughput_tph is None
    assert back.tank("main").inventory_t == 1000.0



def test_proposed_action_is_not_executed_and_has_no_expected_effect():
    action = PendingAction("a1", "2026-01-05T08:00:00", {"ht_reactor_inlet_temp_c": 352.0}, 2.0)
    assert action.executed is False
    assert action.effect_expected_at() is None


def test_confirmation_makes_the_effect_time_known():
    action = PendingAction("a1", "2026-01-05T08:00:00", {"ht_reactor_inlet_temp_c": 352.0}, 2.0)
    confirmed = action.confirm("2026-01-05T08:10:00")
    assert confirmed.executed is True
    assert confirmed.effect_expected_at() == "2026-01-05T10:10:00"
    assert action.executed is False, "исходное действие не должно меняться на месте"


def test_double_confirmation_is_rejected_to_prevent_double_counting():
    action = PendingAction("a1", "2026-01-05T08:00:00", {}, 2.0).confirm("2026-01-05T08:10:00")
    with pytest.raises(ContractError, match="двойному учёту"):
        action.confirm("2026-01-05T08:20:00")


def test_confirmed_status_without_time_is_rejected():
    with pytest.raises(ContractError, match="время подтверждения"):
        PendingAction("a1", "2026-01-05T08:00:00", {}, 2.0, execution_status=CONFIRMED)


def test_confirmation_time_without_confirmed_status_is_rejected():
    with pytest.raises(ContractError, match="без статуса confirmed"):
        PendingAction("a1", "2026-01-05T08:00:00", {}, 2.0, confirmed_at="2026-01-05T08:10:00")


@pytest.mark.parametrize("lag", [-1, 3.5, float("nan")])
def test_response_lag_outside_case_range_is_rejected(lag):
    with pytest.raises(ContractError, match="0–3 часа"):
        PendingAction("a1", "2026-01-05T08:00:00", {}, lag)


def test_only_confirmed_actions_are_reported_as_executed():
    proposed = PendingAction("a1", "2026-01-05T08:00:00", {}, 2.0)
    done = PendingAction("a2", "2026-01-05T07:00:00", {}, 1.0).confirm("2026-01-05T07:05:00")
    state = PlantState("2026-01-05T08:00:00", pending_actions=(proposed, done))
    assert [a.action_id for a in state.confirmed_actions()] == ["a2"]



def test_withdrawal_beyond_inventory_is_an_error_not_a_clamp():
    with pytest.raises(ContractError, match="превышает остаток"):
        tank(inventory_t=50.0).draw(60.0)


def test_withdrawal_reduces_inventory_without_mutating_the_original():
    original = tank(inventory_t=100.0)
    after = original.draw(30.0)
    assert after.inventory_t == 70.0
    assert original.inventory_t == 100.0


def test_tank_without_sulfur_stays_unknown():
    assert TankState("x", True, 10.0, {"sulfur_mgkg": None, "t95_c": 350.0, "cetane_number": 51.0,
                                       "density_kgm3": 836.0}).unknown_properties() == ["sulfur_mgkg"]


def test_missing_optional_property_stays_unknown():
    t = TankState("light", True, 10.0, {"sulfur_mgkg": 6.0})
    assert t.properties["cetane_number"] is None
    assert t.unknown_properties() == ["t95_c", "cetane_number", "density_kgm3"]



def test_forecast_without_values_is_unavailable_rather_than_zero():
    f = ForecastValue("sulfur_mgkg", 2.0, None, None, None, "last_pak")
    assert f.available is False
    assert f.value is None


def test_interval_not_bracketing_the_point_is_rejected():
    with pytest.raises(ContractError, match="не окружают"):
        ForecastValue("sulfur_mgkg", 2.0, 8.0, 9.0, 8.5, "m")


def test_model_cannot_be_used_before_its_calibration_existed():
    f = ForecastValue("sulfur_mgkg", 2.0, 8.0, 7.0, 9.0, "m", valid_from="2026-01-01T00:00:00")
    assert f.usable_at("2025-12-31T23:00:00") is False
    assert f.usable_at("2026-01-02T00:00:00") is True



def test_unknown_check_blocks_the_plan():
    gate = GateResult("p1", (CheckResult("sulfur", PASS, 8.0, 10.0, 0.0),
                             CheckResult("cetane", UNKNOWN, None, None, 0.0,
                                         reason="цетановое число компонента light неизвестно")))
    assert gate.feasible is False
    assert [c.constraint_id for c in gate.unknown_requirements()] == ["cetane"]
    assert gate.first_violation is None, "неизвестность не является нарушением, но и не является допуском"


def test_all_passing_checks_make_the_plan_feasible():
    gate = GateResult("p1", (CheckResult("sulfur", PASS, 8.0, 10.0, 0.0),
                             CheckResult("t95", PASS, 350.0, 360.0, 0.0)))
    assert gate.feasible is True
    assert gate.rejection_reasons() == ()


def test_first_violation_is_the_earliest_one_not_the_worst():
    gate = GateResult("p1", (CheckResult("sulfur", FAIL, 12.0, 10.0, 2.0, reason="поздно"),
                             CheckResult("stock", FAIL, -1.0, 0.0, 0.5, reason="рано")))
    assert gate.first_violation.time_hours == 0.5
    assert gate.first_violation.reason == "рано"


def test_plan_safe_only_at_the_end_still_fails():
    gate = GateResult("p1", tuple(
        CheckResult("sulfur", PASS if t >= 2.0 else FAIL, 9.0 if t >= 2.0 else 12.0, 10.0, t,
                    reason="" if t >= 2.0 else "превышение в переходный период")
        for t in (0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0)))
    assert gate.feasible is False
    assert gate.first_violation.time_hours == 0.0


def test_failing_check_must_name_a_reason():
    with pytest.raises(ContractError, match="назвать причину"):
        CheckResult("sulfur", FAIL, 12.0, 10.0, 0.0)


def test_gate_without_checks_cannot_be_declared_feasible():
    with pytest.raises(ContractError, match="без единой проверки"):
        GateResult("p1", ())


def test_gate_round_trip_keeps_unknown_status():
    gate = GateResult("p1", (CheckResult("cetane", UNKNOWN, None, None, 1.0, reason="нет данных"),))
    back = GateResult.from_dict(json.loads(json.dumps(gate.to_dict())))
    assert back.feasible is False
    assert back.checks[0].status == UNKNOWN
    assert back.checks[0].observed is None



def test_plan_steps_must_start_now_and_increase():
    with pytest.raises(ContractError, match="0 ч"):
        ActionPlan("p", (PlanStep(0.5),))
    with pytest.raises(ContractError, match="по возрастанию"):
        ActionPlan("p", (PlanStep(0.0), PlanStep(2.0), PlanStep(1.0)))


def test_recipe_fractions_must_sum_to_one():
    with pytest.raises(ContractError, match="доли дают"):
        PlanStep(0.0, recipe={"main": 0.7, "reserve": 0.2})


def test_negative_recipe_fraction_is_rejected():
    with pytest.raises(ContractError, match="отрицательные доли"):
        PlanStep(0.0, recipe={"main": 1.2, "reserve": -0.2})


def test_hold_plan_is_recognisable():
    controls = {"ht_reactor_inlet_temp_c": 348.0}
    recipe = {"main": 0.9, "reserve": 0.1}
    hold = ActionPlan("hold", (PlanStep(0.0, controls=controls, recipe=recipe, throughput_tph=100.0),))
    change = ActionPlan("change", (PlanStep(0.0, controls={"ht_reactor_inlet_temp_c": 352.0},
                                            recipe=recipe, throughput_tph=100.0),))
    assert hold.is_hold(controls, recipe) is True
    assert change.is_hold(controls, recipe) is False


def test_plan_step_json_keeps_the_existing_dose_field():
    raw = PlanStep(0.0, additive_dose=0.002).to_dict()
    assert raw["additive_dose_fraction"] == 0.002
    assert "additive_dose" not in raw
    assert PlanStep.from_dict(raw).additive_dose == 0.002


def test_immediate_action_is_the_first_step_only():
    p = plan(steps=[PlanStep(0.0, recipe={"main": 1.0}), PlanStep(2.0, recipe={"main": 0.8, "reserve": 0.2})])
    assert p.immediate.time_hours == 0.0
    assert p.horizon_hours == 2.0



def test_negative_inventory_in_a_trajectory_is_rejected():
    with pytest.raises(ContractError, match="отрицательные остатки"):
        TrajectoryPoint(1.0, {"sulfur_mgkg": 8.0}, {"reserve": -5.0})


def test_unknown_quality_in_a_trajectory_is_preserved():
    point = TrajectoryPoint(0.0, {"sulfur_mgkg": 8.0}, {"main": 100.0})
    assert point.qualities["cetane_number"] is None
    assert point.unknown_qualities() == ["t95_c", "cetane_number", "density_kgm3"]


def test_terminal_inventory_comes_from_the_last_point():
    est = TrajectoryEstimate("p", (TrajectoryPoint(0.0, {"sulfur_mgkg": 8.0}, {"r": 100.0}),
                                   TrajectoryPoint(3.0, {"sulfur_mgkg": 9.0}, {"r": 20.0})))
    assert est.terminal_inventory == {"r": 20.0}



def test_refusal_cannot_carry_a_plan():
    with pytest.raises(ContractError, match="отказ не может нести"):
        Decision("d", "2026-01-05T08:00:00", REFUSE, "нет данных", "baseline", selected_plan=plan())


def test_recommendation_requires_a_plan():
    with pytest.raises(ContractError, match="требует выбранного плана"):
        Decision("d", "2026-01-05T08:00:00", RECOMMEND_SCENARIO, "почему-то", "baseline")


def test_plan_failing_the_gate_cannot_be_selected():
    gate = GateResult("p1", (CheckResult("sulfur", FAIL, 12.0, 10.0, 0.0, reason="выше предела"),))
    with pytest.raises(ContractError, match="не прошедший обязательные проверки"):
        Decision("d", "2026-01-05T08:00:00", HOLD, "режим сохранён", "baseline",
                 selected_plan=plan(), gate=gate)


def test_commercial_release_can_never_be_granted():
    with pytest.raises(ContractError, match="промышленного выпуска"):
        Decision("d", "2026-01-05T08:00:00", REFUSE, "нет данных", "baseline",
                 commercial_release_allowed=True)


def test_decision_must_state_a_reason():
    with pytest.raises(ContractError, match="назвать причину"):
        Decision("d", "2026-01-05T08:00:00", REFUSE, "   ", "baseline")


def test_decision_round_trip_survives_json_without_losing_status_or_time():
    gate = GateResult("p1", (CheckResult("sulfur", PASS, 8.0, 10.0, 0.0),))
    decision = Decision("d1", "2026-01-05T08:00:00", HOLD, "режим проходит ограничения", "baseline",
                        selected_plan=plan(), expected_outcome=trajectory(), gate=gate,
                        forecasts=(ForecastValue("sulfur_mgkg", 2.0, 8.0, 7.0, 9.0, "last_pak"),
                                   ForecastValue("cetane_number", 2.0, None, None, None, "unavailable")),
                        next_review_at="2026-01-05T08:30:00",
                        reconsideration_conditions=("новый анализ ЛИМС",))
    back = Decision.from_dict(json.loads(json.dumps(decision.to_dict())))
    assert back.to_dict() == decision.to_dict()
    assert back.status == HOLD
    assert back.forecasts[1].available is False
    assert back.next_review_at == "2026-01-05T08:30:00"
    assert back.immediate_action.throughput_tph == 100.0
    assert back.commercial_release_allowed is False
