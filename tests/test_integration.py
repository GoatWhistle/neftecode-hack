"""End-to-end checks: the requirements of T02 and the error chains that must not be bypassable.

Each test here goes through the real components rather than a stub, because the defects worth
catching are the ones that appear only when the parts are wired together.
"""
import copy
import json
from pathlib import Path

import pandas as pd
import pytest

from neftecode.domain.shared.primitives import ContractError
from neftecode.domain.monitoring.entities import Observation, PlantState
from neftecode.domain.shared.actions import PendingAction
from neftecode.demo import Demo, apply_change
from neftecode.application.services.explain import explain
from neftecode.domain.advisory.gate import TrajectoryPoint, check_plan
from neftecode.domain.production.inventory import InventoryLedger
from neftecode.application.use_cases.make_decision import AgentError, MakeDecision
from neftecode.application.use_cases.plan_operation import PlanOperation, PlanCandidate, PlanStep
from neftecode.application.use_cases.replay_decisions import ExecutionState, ReplayDecisions, ReplayError, SIMULATED
from neftecode.scenario import ScenarioError, load_scenario, parse_scenario
from neftecode.application.services.trust import DataTrustAgent
from neftecode.robustness import RobustnessCheck

SCENARIOS = Path("config/scenarios")
BASELINE = SCENARIOS / "baseline.json"
SOUR = SCENARIOS / "sour_crude.json"
BUDGET = 300


def raw(path=BASELINE):
    return json.loads(Path(path).read_text())


def decide(path=BASELINE, **kw):
    scenario = load_scenario(path)
    scenario_raw = raw(path)
    return scenario, MakeDecision(scenario, robustness_evaluator=RobustnessCheck(
        scenario, scenario_raw)).decide(budget=BUDGET, raw_scenario=scenario_raw, **kw)


def healthy_state():
    return {"decision_time": "2026-01-05T08:00:00",
            "lab_value": 8.0, "lab_age_hours": 5.0, "lab_usable": True,
            "pak_value": 8.4, "pak_age_minutes": 10.0, "pak_usable": True,
            "pak_frozen": False, "pak_conflict": False, "telemetry_missing_fraction": 0.0}


# --- Error chain: data from the future ---

def test_an_observation_not_yet_available_cannot_enter_the_state():
    late = Observation("lab.sulfur", "ЛИМС", 8.0, "мг/кг",
                       "2026-01-05T04:00:00", "2026-01-05T08:00:00")
    with pytest.raises(ContractError, match="утечка из будущего"):
        PlantState("2026-01-05T06:00:00", observations=(late,))
    assert PlantState("2026-01-05T08:00:00", observations=(late,)).observations


def test_a_model_cannot_be_used_before_its_calibration_existed():
    from neftecode.runtime import validate_origin
    with pytest.raises(ValueError, match="утечк"):
        validate_origin("2025-12-31T23:00:00", {"config": {"calibration_end": "2026-01-01"}})


def test_the_future_truth_never_reaches_a_replayed_decision():
    scenario = load_scenario(SOUR)
    document = raw(SOUR)
    replay = ReplayDecisions(scenario, document, budget=BUDGET,
                             robustness_evaluator=RobustnessCheck(scenario, document))
    plain = replay.step(SIMULATED)
    marker = 424242.125
    seeded = replay.step(SIMULATED, future_truth={"actual_sulfur": marker})
    assert plain["decision"]["decision_id"] == seeded["decision"]["decision_id"]
    assert "424242" not in json.dumps(seeded["decision"], ensure_ascii=False)
    assert seeded["evaluation_only"]["actual_sulfur"] == marker


# --- Error chain: units ---

def test_a_wrong_unit_is_refused_at_load_not_converted():
    broken = raw()
    broken["tanks"][0]["inventory"]["unit"] = "кг"
    with pytest.raises(ScenarioError, match="не совпадает с ожидаемой"):
        parse_scenario(broken)


def test_a_bare_number_cannot_pose_as_a_measured_quantity():
    broken = raw()
    broken["crude"]["sulfur_wt_pct"] = 1.35
    with pytest.raises(ScenarioError, match="ожидается объект"):
        parse_scenario(broken)


def test_a_scenario_constant_is_never_reported_as_measured():
    scenario = load_scenario(BASELINE)
    assert scenario.tank("reserve").inventory.measured is False
    assert scenario.product.limits["sulfur_mgkg"].measured is True


# --- Error chain: NaN and unknown quality ---

def test_nan_anywhere_becomes_unknown_and_blocks_the_plan():
    scenario = load_scenario(BASELINE)
    steps = [TrajectoryPoint(t, {"sulfur_mgkg": float("nan"), "t95_c": 350.0, "cetane_number": 51.5},
                            {"ht_reactor_inlet_temp_c": 348.0}, {"main": 100.0},
                            {"main": 1.0}, 100.0)
             for t in (0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0)]
    gate = check_plan("p", steps, scenario)
    assert gate.feasible is False
    assert any(c.status == "unknown" for c in gate.checks)


def test_a_component_without_cetane_makes_the_blend_unknown_and_blocks_it():
    scenario = load_scenario(BASELINE)
    planner = PlanOperation(scenario)
    plan = PlanCandidate("light_only",
                         (PlanStep(0.0, planner.base_controls(), {"light": 1.0}, 20.0),))
    evaluation = planner.evaluate(plan)
    unknown = {c.constraint_id for c in evaluation.gate.unknown_requirements()}
    assert "quality.cetane_number" in unknown
    assert evaluation.feasible is False


def test_an_unknown_limit_blocks_rather_than_passes():
    broken = raw()
    broken["product"]["cetane_number"] = None
    scenario = parse_scenario(broken)
    decision = MakeDecision(scenario).decide(budget=BUDGET)
    assert decision["status"] == "refuse", "неизвестный предел не может пройти молча"


# --- Error chain: an empty tank ---

def test_an_empty_tank_cannot_be_drawn_from():
    empty = raw()
    for tank in empty["tanks"]:
        if tank["tank_id"] == "reserve":
            tank["inventory"]["value"] = 0.0
    scenario = parse_scenario(empty)
    ledger = InventoryLedger(scenario)
    result = ledger.run_plan([(0.0, {"main": 0.8, "reserve": 0.2}, 100.0)])
    assert result["feasible"] is False
    assert result["first_failure"] is not None


def test_the_advisor_does_not_propose_a_recipe_the_stock_cannot_carry():
    empty = raw(SOUR)
    for tank in empty["tanks"]:
        if tank["tank_id"] == "reserve":
            tank["inventory"]["value"] = 1.0
    scenario = parse_scenario(empty)
    decision = MakeDecision(scenario).decide(budget=BUDGET)
    if decision["selected_plan"] is not None:
        for step in decision["selected_plan"]["steps"]:
            used = step["throughput_tph"] * step["recipe"].get("reserve", 0.0) * 3.0
            assert used <= 1.0 + 1e-6


# --- Error chain: the delayed effect ---

def test_a_correction_cannot_help_before_its_lag_has_passed():
    from neftecode.domain.production.process import ChainModel
    chain = ChainModel(load_scenario(SOUR))
    pending = ((0.0, {"ht_reactor_inlet_temp_c": 356.0}),)
    assert chain.run_at(1.9, pending).sulfur_mgkg == pytest.approx(chain.run_at(1.9).sulfur_mgkg)
    assert chain.run_at(2.0, pending).sulfur_mgkg < chain.run_at(1.9, pending).sulfur_mgkg


def test_a_plan_relying_on_an_immediate_effect_is_rejected_by_the_gate():
    """The transition must be covered by the blend, not by a correction that has not acted."""
    scenario = load_scenario(SOUR)
    planner = PlanOperation(scenario)
    naive = PlanCandidate("naive", (PlanStep(
        0.0, {**planner.base_controls(), "ht_reactor_inlet_temp_c": 360.0},
        {"main": 1.0, "reserve": 0.0, "light": 0.0}, 80.0),))
    evaluation = planner.evaluate(naive)
    assert evaluation.feasible is False
    assert evaluation.gate.first_violation.time_hours < 2.0


# --- Error chain: an impossible plan ---

def test_an_impossible_plan_yields_a_refusal_not_a_crash():
    scenario, decision = decide(SCENARIOS / "no_feasible.json")
    assert decision["status"] == "refuse"
    assert decision["selected_plan"] is None
    assert explain(decision, scenario)["next_steps"]


def test_a_released_plan_always_carries_a_passing_gate():
    for path in (BASELINE, SOUR):
        _, decision = decide(path)
        assert decision["gate"]["feasible"] is True


def test_no_decision_ever_permits_commercial_release():
    for path in sorted(SCENARIOS.glob("*.json")):
        _, decision = decide(path)
        assert decision["commercial_release_allowed"] is False


# --- Error chain: an agent failure ---

def test_a_failing_optimizer_raises_rather_than_returning_a_decision():
    orchestrator = MakeDecision(load_scenario(BASELINE))

    def broken(budget):
        raise ValueError("оптимизатор сломан")

    orchestrator.planner.build_plans = broken
    with pytest.raises(AgentError, match="не смог построить"):
        orchestrator.decide(budget=BUDGET)


def test_unusable_data_stops_the_loop_before_any_model_runs():
    scenario = load_scenario(BASELINE)
    state = dict(healthy_state(), lab_value=None, lab_usable=False,
                 pak_frozen=True, pak_usable=False)
    decision = MakeDecision(scenario).decide(state=state, budget=BUDGET)
    assert decision["status"] == "refuse"
    assert not any(t.get("agent") == "optimizer" for t in decision["trace"])


# --- Error chain: applying an action twice ---

def test_the_same_action_cannot_be_confirmed_twice():
    state = ExecutionState.from_scenario(load_scenario(SOUR))
    action = PendingAction("a1", "2026-01-05T08:00:00", {"ht_reactor_inlet_temp_c": 352.0}, 2.0)
    state = state.confirm(action, "2026-01-05T08:05:00")
    with pytest.raises(ReplayError, match="двойному учёту"):
        state.confirm(action, "2026-01-05T08:10:00")


def test_repeating_the_same_correction_does_not_double_its_effect():
    from neftecode.domain.production.process import ChainModel
    chain = ChainModel(load_scenario(SOUR))
    once = chain.run_at(3.0, ((0.0, {"ht_reactor_inlet_temp_c": 354.0}),)).sulfur_mgkg
    twice = chain.run_at(3.0, ((0.0, {"ht_reactor_inlet_temp_c": 354.0}),
                               (0.5, {"ht_reactor_inlet_temp_c": 354.0}))).sulfur_mgkg
    assert once == pytest.approx(twice)


def test_issuing_advice_twice_does_not_change_the_plant():
    scenario = load_scenario(SOUR)
    document = raw(SOUR)
    replay = ReplayDecisions(scenario, document, budget=BUDGET,
                             robustness_evaluator=RobustnessCheck(scenario, document))
    run = replay.run([{"at": "2026-01-05T08:00:00"}, {"at": "2026-01-05T08:30:00"}], SIMULATED)
    assert run["final_execution"]["executed"] == []


# --- Requirements of T02, checked end to end ---

def test_the_hard_sulfur_limit_holds_in_every_scenario():
    for path in sorted(SCENARIOS.glob("*.json")):
        scenario = load_scenario(path)
        assert scenario.product.limit_value("sulfur_mgkg") <= 10.0


def test_fractions_always_sum_to_one_in_a_released_plan():
    for path in (BASELINE, SOUR):
        _, decision = decide(path)
        for step in decision["selected_plan"]["steps"]:
            assert sum(step["recipe"].values()) == pytest.approx(1.0)


def test_quality_outranks_economics_in_every_released_plan():
    """No plan is released with a quality violation, whatever it earns."""
    for path in (BASELINE, SOUR):
        _, decision = decide(path)
        failing = [c for c in decision["gate"]["checks"]
                   if c["constraint_id"].startswith("quality.") and c["status"] != "pass"]
        assert not failing


def test_the_response_lag_of_every_scenario_is_within_the_case_bounds():
    for path in sorted(SCENARIOS.glob("*.json")):
        scenario = load_scenario(path)
        for stage in scenario.stages.values():
            assert 0 <= stage.response_lag_hours.value <= 3


def test_every_horizon_is_within_the_case_bounds():
    for path in sorted(SCENARIOS.glob("*.json")):
        assert 0 < load_scenario(path).horizon.hours <= 3


def test_the_experiment_config_matches_the_confirmed_bounds():
    from neftecode.data import check_time_assumptions
    bounds = check_time_assumptions(json.loads(Path("config/experiment.json").read_text()))
    assert bounds["lab_delay_hours"] <= 4.0
    assert 0 < bounds["horizon_hours"] <= 3.0


def test_control_candidates_contain_no_quality_analyser():
    config = json.loads(Path("config/experiment.json").read_text())
    assert "ht.P13" not in config["control_candidates"], "анализатор качества не управляющий тег"
    assert "ht.T5" not in config["control_candidates"]


def test_every_scenario_declares_itself_synthetic_and_lists_assumptions():
    for path in sorted(SCENARIOS.glob("*.json")):
        scenario = load_scenario(path)
        assert scenario.kind == "synthetic_blending_scenario"
        assert scenario.assumptions


def test_the_whole_pipeline_runs_for_every_scenario():
    for path in sorted(SCENARIOS.glob("*.json")):
        scenario, decision = decide(path)
        explanation = explain(decision, scenario)
        assert decision["status"] in ("hold", "recommend_scenario", "refuse")
        assert explanation


def test_each_scenario_matches_its_recorded_expectation():
    for path in sorted(SCENARIOS.glob("*.json")):
        scenario, decision = decide(path)
        expected = scenario.expected["outcome"]
        if expected == "recommend_or_refuse":
            assert decision["status"] in ("recommend_scenario", "refuse")
        else:
            assert decision["status"] == expected


def test_the_demo_and_the_advisor_agree_on_the_same_conditions():
    scenario, decision = decide(BASELINE)
    demo = Demo.from_path(BASELINE, budget=BUDGET).run()
    assert demo["decision"]["status"] == decision["status"]
