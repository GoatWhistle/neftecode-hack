"""Replay: the same core on history and in simulation, with the two kept apart."""
import json
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
                     "confirmed_at": "2026-01-05T08:05:00",
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


def test_the_future_value_is_kept_outside_the_decision_object():
    record = replay().step(SIMULATED, future_truth={"actual_sulfur": 42.0})
    assert "42" not in json.dumps(record["decision"], ensure_ascii=False)


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
