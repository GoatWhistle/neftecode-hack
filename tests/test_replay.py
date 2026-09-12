"""Replay: the same core on history and in simulation, with the two kept apart."""
import json
from dataclasses import replace
from pathlib import Path

import pytest

from neftecode.contracts import PendingAction
from neftecode.replay import (HISTORICAL, SIMULATED, ExecutionState, Replay, ReplayError,
                              compare_runs, versions)
from neftecode.scenario import load_scenario

SOUR = Path("config/scenarios/sour_crude.json")
BASELINE = Path("config/scenarios/baseline.json")
BUDGET = 300


def replay(path=SOUR):
    return Replay(load_scenario(path), json.loads(Path(path).read_text()), budget=BUDGET)


def moments():
    return [
        {"at": "2026-01-05T08:00:00"},
        {"at": "2026-01-05T08:30:00",
         "confirm": {"action_id": "a1", "proposed_at": "2026-01-05T08:00:00",
                     "confirmed_at": "2026-01-05T08:30:00",
                     "controls": {"ht_reactor_inlet_temp_c": 352.0}}},
        {"at": "2026-01-05T09:00:00"},
    ]


# --- Reproducibility ---

def test_two_runs_give_numerically_identical_decisions():
    r = replay()
    first, second = r.run(moments(), SIMULATED), r.run(moments(), SIMULATED)
    comparison = compare_runs(first, second)
    assert comparison["identical"] is True
    assert comparison["n"] == len(moments())


def test_a_single_step_is_reproducible():
    r = replay()
    assert r.step(SIMULATED)["decision"]["decision_id"] == r.step(SIMULATED)["decision"]["decision_id"]


def test_every_record_carries_the_versions_it_depended_on():
    record = replay().step(SIMULATED)
    assert record["versions"]["scenario_id"] == "sour_crude"
    assert len(record["versions"]["scenario_fingerprint"]) == 16
    assert record["versions"]["models"]["hydrotreating"]


def test_a_changed_scenario_changes_the_fingerprint():
    raw = json.loads(SOUR.read_text())
    scenario = load_scenario(SOUR)
    altered = dict(raw, id="sour_crude")
    altered["crude"] = dict(raw["crude"])
    altered["crude"]["sulfur_wt_pct"] = dict(raw["crude"]["sulfur_wt_pct"], value=2.5)
    assert versions(scenario, raw)["scenario_fingerprint"] != \
           versions(scenario, altered)["scenario_fingerprint"]


# --- Pause and resume lose nothing ---

def test_pausing_and_resuming_keeps_stock_and_executed_actions():
    r = replay()
    run = r.run(moments(), SIMULATED)
    restored = ExecutionState.from_dict(run["final_execution"])
    assert len(restored.executed) == 1
    assert restored.tanks["reserve"].inventory_t == \
           pytest.approx(run["final_execution"]["tanks"]["reserve"]["inventory_t"])


def test_execution_state_survives_a_json_round_trip():
    state = ExecutionState.from_scenario(load_scenario(SOUR))
    action = PendingAction("a1", "2026-01-05T08:00:00", {"ht_reactor_inlet_temp_c": 352.0}, 2.0)
    state = state.confirm(action, "2026-01-05T08:05:00").advance(0.5)
    restored = ExecutionState.from_dict(json.loads(json.dumps(state.to_dict())))
    assert restored.clock_hours == 0.5
    assert restored.executed[0].executed is True
    assert restored.tanks.keys() == state.tanks.keys()


def test_resuming_from_a_saved_state_continues_rather_than_restarting():
    r = replay()
    saved = ExecutionState.from_dict(r.run(moments()[:2], SIMULATED)["final_execution"])
    continued = r.run(moments()[2:], SIMULATED, execution=saved)
    assert len(continued["final_execution"]["executed"]) == 1, "исполненное действие потеряно"


def test_split_resume_matches_uninterrupted_state_and_decisions():
    r = replay()
    uninterrupted = r.run(moments(), SIMULATED)
    saved = ExecutionState.from_dict(r.run(moments()[:2], SIMULATED)["final_execution"])
    resumed = r.run(moments()[2:], SIMULATED, execution=saved)
    assert resumed["final_execution"]["clock_hours"] == pytest.approx(
        uninterrupted["final_execution"]["clock_hours"])
    assert resumed["final_execution"]["tanks"] == uninterrupted["final_execution"]["tanks"]
    assert [x["decision"]["decision_id"] for x in resumed["records"]] == [
        x["decision"]["decision_id"] for x in uninterrupted["records"][2:]]


# --- Advice is not execution ---

def test_a_decision_alone_does_not_execute_anything():
    r = replay()
    run = r.run([{"at": "2026-01-05T08:00:00"}], SIMULATED)
    assert run["final_execution"]["executed"] == [], "совет сам по себе не исполняется"


def test_only_a_confirmation_puts_an_action_into_the_execution_state():
    run = replay().run(moments(), SIMULATED)
    assert len(run["final_execution"]["executed"]) == 1
    assert run["final_execution"]["executed"][0]["execution_status"] == "confirmed"


def test_confirming_the_same_action_twice_is_refused():
    state = ExecutionState.from_scenario(load_scenario(SOUR))
    action = PendingAction("a1", "2026-01-05T08:00:00", {"ht_reactor_inlet_temp_c": 352.0}, 2.0)
    state = state.confirm(action, "2026-01-05T08:05:00")
    with pytest.raises(ReplayError, match="двойному учёту"):
        state.confirm(action, "2026-01-05T08:10:00")


def test_drawing_from_the_execution_state_does_not_mutate_it():
    state = ExecutionState.from_scenario(load_scenario(SOUR))
    before = state.tanks["reserve"].inventory_t
    state.draw({"reserve": 10.0})
    assert state.tanks["reserve"].inventory_t == before


def test_a_draw_returns_a_new_state_with_the_stock_reduced():
    state = ExecutionState.from_scenario(load_scenario(SOUR))
    after = state.draw({"reserve": 10.0})
    assert after.tanks["reserve"].inventory_t == pytest.approx(
        state.tanks["reserve"].inventory_t - 10.0)


def test_simulated_run_spends_current_recipe_between_moments():
    state = ExecutionState.from_scenario(load_scenario(SOUR))
    initial = state.tanks["reserve"].inventory_t
    result = replay().run([{"at": "2026-01-05T08:00:00"},
                           {"at": "2026-01-05T09:00:00"}], SIMULATED)
    assert result["final_execution"]["tanks"]["reserve"]["inventory_t"] < initial


def test_one_tonne_reserve_changes_decision_and_never_proposes_twenty_percent():
    r = replay()
    state = ExecutionState.from_scenario(load_scenario(SOUR))
    low = replace(state, tanks={**state.tanks,
                                "reserve": replace(state.tanks["reserve"], inventory_t=1.0)})
    normal = r.step(SIMULATED, execution=state)["decision"]
    constrained = r.step(SIMULATED, execution=low)["decision"]
    assert constrained["decision_id"] != normal["decision_id"]
    assert constrained["status"] == "refuse" or constrained["selected_plan"] is None or all(
        step["recipe"].get("reserve", 0.0) < 0.2 for step in constrained["selected_plan"]["steps"])


def test_confirmed_action_two_hours_old_changes_inflow_properties():
    r = replay()
    state = ExecutionState.from_scenario(load_scenario(SOUR))
    action = PendingAction("old", "2026-01-05T08:00:00",
                           {"avt_furnace_outlet_temp_c": 400.0}, 2.0)
    state = replace(state.confirm(action, "2026-01-05T08:00:00"), last_at="2026-01-05T10:00:00")
    before = state.tanks["main"].properties["t95_c"]
    advanced = r._advance_to(state, "2026-01-05T12:00:00")
    assert advanced.tanks["main"].properties["t95_c"] != pytest.approx(before)
    assert advanced.confirmed_controls()[0][0] == pytest.approx(-4.0)


def test_confirmed_controls_keep_their_elapsed_time():
    state = ExecutionState.from_scenario(load_scenario(SOUR))
    action = PendingAction("old", "2026-01-05T06:00:00", {"ht_reactor_inlet_temp_c": 352.0}, 2.0)
    state = state.confirm(action, "2026-01-05T06:00:00")
    state = state.advance(2.0)
    state = replace(state, last_at="2026-01-05T08:00:00")
    assert state.confirmed_controls()[0][0] == pytest.approx(-2.0)


# --- History and simulation stay apart ---

def test_history_cannot_be_continued_as_if_advice_had_been_executed():
    state = ExecutionState.from_scenario(load_scenario(SOUR))
    action = PendingAction("a1", "2026-01-05T08:00:00", {"ht_reactor_inlet_temp_c": 352.0}, 2.0)
    state = state.confirm(action, "2026-01-05T08:05:00")
    with pytest.raises(ReplayError, match="будто"):
        replay().step(HISTORICAL, execution=state)


def test_history_without_executed_actions_is_allowed():
    record = replay().step(HISTORICAL, execution=ExecutionState.from_scenario(load_scenario(SOUR)))
    assert record["mode"] == HISTORICAL


def test_each_mode_labels_its_own_result():
    r = replay()
    assert "не показывает, что произошло бы" in r.step(HISTORICAL)["note"]
    assert "не на заводе" in r.step(SIMULATED)["note"]


def test_the_run_states_that_the_two_are_not_mixed():
    assert "не смешиваются" in replay().run(moments(), SIMULATED)["separation"]


def test_an_unknown_mode_is_refused():
    with pytest.raises(ReplayError, match="Неизвестный режим"):
        replay().step("как-нибудь")


def test_compare_runs_with_different_lengths_is_not_identical():
    first = replay().run([{"at": "2026-01-05T08:00:00"}], SIMULATED)
    second = replay().run([{"at": "2026-01-05T08:00:00"}, {"at": "2026-01-05T08:30:00"}], SIMULATED)
    assert compare_runs(first, second)["identical"] is False


def test_simulated_time_and_draw_inputs_reject_invalid_values():
    state = ExecutionState.from_scenario(load_scenario(SOUR))
    with pytest.raises(ReplayError):
        state.advance(float("nan"))
    with pytest.raises(ReplayError):
        state.draw({"reserve": float("inf")})
    with pytest.raises(ReplayError):
        replay().run([{"at": "2026-01-05T08:30:00"}, {"at": "2026-01-05T08:00:00"}], SIMULATED)


# --- Future truth reaches the evaluator only ---

def test_the_future_value_never_enters_the_decision():
    r = replay()
    plain = r.step(SIMULATED)
    with_truth = r.step(SIMULATED, future_truth={"actual_sulfur": 42.0})
    assert plain["decision"]["decision_id"] == with_truth["decision"]["decision_id"], \
        "будущее значение изменило решение"


def test_the_future_value_is_returned_for_evaluation():
    record = replay().step(SIMULATED, future_truth={"actual_sulfur": 42.0})
    assert record["evaluation_only"]["actual_sulfur"] == 42.0


def test_changing_future_truth_does_not_change_the_decision():
    r = replay()
    plain = r.step(SIMULATED)
    with_truth = r.step(SIMULATED, future_truth={"actual_sulfur": 42.0})
    assert with_truth["decision"] == plain["decision"]


# --- The same core is used in both modes ---

def test_both_modes_run_the_same_decision_core():
    r = replay(BASELINE)
    assert r.step(HISTORICAL)["decision"]["status"] == r.step(SIMULATED)["decision"]["status"]


def test_a_confirmed_action_changes_what_the_advisor_proposes_next():
    r = replay()
    state = ExecutionState.from_scenario(load_scenario(SOUR))
    before = r.step(SIMULATED, execution=state)["decision"]
    action = PendingAction("a1", "2026-01-05T08:00:00", {"ht_reactor_inlet_temp_c": 360.0}, 2.0)
    after = r.step(SIMULATED, execution=state.confirm(action, "2026-01-05T08:05:00"))["decision"]
    assert before["decision_id"] != after["decision_id"]


def test_saved_current_operation_drives_inflow_without_an_action_log():
    from neftecode.planner import Planner, PlanCandidate, PlanStepSpec
    r = replay()
    state = ExecutionState.from_scenario(load_scenario(SOUR))
    operation = {**state.current_operation, "controls": {
        **state.current_operation["controls"], "avt_furnace_outlet_temp_c": 400.0}}
    state = replace(state.set_operation(operation), last_at="2026-01-05T08:00:00")
    hot = r._advance_to(state, "2026-01-05T08:30:00")
    cold_state = replace(ExecutionState.from_scenario(load_scenario(SOUR)), last_at=state.last_at)
    cold = r._advance_to(cold_state, "2026-01-05T08:30:00")
    assert hot.tanks["main"].properties["t95_c"] > cold.tanks["main"].properties["t95_c"]
    p = Planner(r.scenario)
    plans, _ = p.build_plans(100, current_operation=operation)
    hold = plans[0]
    assert hold.steps[0].controls["avt_furnace_outlet_temp_c"] == 400.0
    evaluation = p.evaluate(hold, current_operation=operation)
    observed = [c.observed for c in evaluation.gate.checks
                if c.constraint_id == "control.avt_furnace_outlet_temp_c"]
    assert all(value == 400.0 for value in observed)


def test_current_recipe_flow_and_dose_define_hold_and_screen_baseline():
    from neftecode.planner import Planner
    r = replay()
    state = ExecutionState.from_scenario(load_scenario(SOUR))
    operation = {**state.current_operation, "recipe": {"main": .8, "reserve": .2},
                 "throughput_tph": 50.0, "additive_dose": .015}
    state = state.set_operation(operation)
    plans, _ = Planner(r.scenario).build_plans(100, current_operation=operation)
    hold = plans[0].steps[0]
    assert hold.recipe["reserve"] == .2
    assert hold.throughput_tph == 50.0
    assert hold.additive_dose == .015
    assert r.step(SIMULATED, execution=state)["decision"]["current_operation"] == operation
