import json
from pathlib import Path

import pytest

from neftecode.domain.shared.primitives import HOLD, RECOMMEND_SCENARIO, REFUSE
from neftecode.application.use_cases.make_decision import (MAX_ROUNDS, AgentError, MakeDecision, QualityReview,
                                    ReliabilityReview)
from neftecode.infrastructure.config.scenario import load_scenario, parse_scenario

BASELINE = Path("config/scenarios/baseline.json")
SOUR = Path("config/scenarios/sour_crude.json")
NO_FEASIBLE = Path("config/scenarios/no_feasible.json")
BUDGET = 400


def orchestrator(path=BASELINE):
    return MakeDecision(load_scenario(path))


def decide(path=BASELINE, **kw):
    return orchestrator(path).decide(budget=BUDGET, **kw)


def rounds_of(decision):
    return next(t for t in decision["trace"] if t.get("agent") == "optimizer")["rounds"]


def healthy_state():
    return {"decision_time": "2026-01-05T08:00:00",
            "lab_value": 8.0, "lab_age_hours": 5.0, "lab_usable": True,
            "pak_value": 8.4, "pak_age_minutes": 10.0, "pak_usable": True,
            "pak_frozen": False, "pak_conflict": False, "telemetry_missing_fraction": 0.0}



def test_a_normal_scenario_holds_the_regime():
    decision = decide(BASELINE)
    assert decision["status"] == HOLD
    assert decision["selected_plan"]["changes"] == 0


def test_a_problem_scenario_produces_a_scenario_recommendation():
    decision = decide(SOUR)
    assert decision["status"] == RECOMMEND_SCENARIO
    assert decision["selected_plan"] is not None
    assert decision["immediate_action"] is not None


def test_an_impossible_scenario_produces_a_refusal():
    decision = decide(NO_FEASIBLE)
    assert decision["status"] == REFUSE
    assert decision["selected_plan"] is None
    assert decision["refusal"]["kind"] == "no_feasible_plan"


def test_no_status_ever_allows_commercial_release():
    for path in (BASELINE, SOUR, NO_FEASIBLE):
        assert decide(path)["commercial_release_allowed"] is False


def test_a_refusal_carries_no_plan_and_a_recommendation_always_does():
    refusal = decide(NO_FEASIBLE)
    assert refusal["selected_plan"] is None and refusal["immediate_action"] is None
    recommendation = decide(SOUR)
    assert recommendation["selected_plan"] is not None



def test_unusable_data_refuses_before_any_model_runs():
    state = dict(healthy_state(), lab_value=None, lab_usable=False, pak_frozen=True, pak_usable=False)
    decision = decide(BASELINE, state=state)
    assert decision["status"] == REFUSE
    assert decision["refusal"]["kind"] == "data"
    assert not any(t.get("agent") == "optimizer" for t in decision["trace"]), \
        "оптимизатор не должен запускаться на недостоверных данных"


def test_the_data_refusal_names_what_is_missing():
    state = dict(healthy_state(), lab_value=None, lab_usable=False, pak_frozen=True, pak_usable=False)
    decision = decide(BASELINE, state=state)
    assert decision["refusal"]["missing"]


def test_healthy_data_lets_the_loop_proceed():
    decision = decide(BASELINE, state=healthy_state())
    assert decision["status"] == HOLD
    assert decision["trace"][0]["agent"] == "data"
    assert decision["trace"][0]["usable"] is True


def test_request_operation_is_not_stored_on_the_reusable_use_case():
    scenario = load_scenario(BASELINE)
    raw = json.loads(BASELINE.read_text(encoding="utf-8"))

    class RobustnessSpy:
        seen = None

        def evaluate(self, scenario, document, plan, confirmed, tanks, current_operation):
            self.seen = current_operation
            return {"held": True, "perturbations_evaluated": 1, "violated": 0,
                    "fragile": False}

    robustness = RobustnessSpy()
    engine = MakeDecision(scenario, robustness_evaluator=robustness)
    operation = {
        "controls": engine.planner.base_controls(),
        "recipe": {"main": 0.85, "reserve": 0.15, "light": 0.0},
        "throughput_tph": 90.0,
        "additive_dose": 0.0,
    }
    built_with, evaluated_with = [], []
    build_plans = engine.planner.build_plans
    evaluate = engine.planner.evaluate

    def record_build(budget, current_operation=None):
        built_with.append(current_operation)
        return build_plans(budget, current_operation=current_operation)

    def record_evaluation(plan, confirmed=(), initial_tanks=None, current_operation=None):
        evaluated_with.append(current_operation)
        return evaluate(plan, confirmed, initial_tanks, current_operation)

    engine.planner.build_plans = record_build
    engine.planner.evaluate = record_evaluation

    first = engine.decide(
        budget=BUDGET, raw_scenario=raw, current_operation=operation
    )
    second = engine.decide(budget=BUDGET)

    assert first["current_operation"] == operation
    assert built_with[0] == operation
    assert evaluated_with[0] == operation
    assert robustness.seen == operation
    assert second["current_operation"] is None
    assert not hasattr(engine, "_current_operation")



def test_a_veto_creates_feedback_candidates_for_the_following_round():
    decision = decide(NO_FEASIBLE)
    loop = rounds_of(decision)
    assert len(loop) >= 2, "цикл обязан сделать повторный поиск после запретов"
    assert loop[0]["restriction_added"], "первый раунд обязан выдать конкретные запреты"
    assert any(":feedback:" in candidate_id for candidate_id in loop[1]["candidate_ids"])


def test_quality_rejection_produces_a_physically_different_feasible_plan():
    from neftecode.application.use_cases.plan_operation import PlanCandidate, PlanStep
    from neftecode.infrastructure.config.scenario import parse_scenario
    raw = json.loads(BASELINE.read_text(encoding="utf-8"))
    raw["product"]["sulfur_mgkg"]["value"] = 7.0
    raw["current_operation"]["throughput"]["value"] = 20.0
    raw["current_operation"]["recipe"] = {"main": 1.0}
    engine = MakeDecision(parse_scenario(raw))
    original = PlanCandidate("initial", (PlanStep(0.0, engine.planner.base_controls(),
                                                     {"main": 1.0}, 20.0),), 0)
    engine.planner.build_plans = lambda budget: ([original], {})
    assert not engine.planner.evaluate(original).feasible
    decision = engine.decide(budget=20)
    assert rounds_of(decision)[0]["feasible"] == 0
    assert decision["status"] == RECOMMEND_SCENARIO
    assert decision["immediate_action"]["recipe"] != original.steps[0].recipe
    assert decision["gate"]["feasible"] is True


def test_agent_veto_of_best_candidate_selects_another_approved_plan():
    class VetoHold:
        def review(self, evaluation):
            veto = evaluation.candidate.candidate_id == "hold"
            return {"agent": "quality", "checked": 1, "passed": 0 if veto else 1,
                    "vetoes": ["hold запрещён политикой"] if veto else [], "unknown": [],
                    "verdict": "fail" if veto else "pass"}

    decision = MakeDecision(load_scenario(BASELINE), quality=VetoHold()).decide(budget=BUDGET)
    assert decision["status"] == RECOMMEND_SCENARIO
    assert decision["selected_plan"]["plan_id"] != "hold"


def test_fail_all_or_incomplete_agent_cannot_release_a_plan():
    class FailAll:
        def review(self, evaluation):
            return {"agent": "quality", "checked": 1, "passed": 0,
                    "vetoes": ["запрет"], "unknown": [], "verdict": "fail"}

    class IncompletePass:
        def review(self, evaluation):
            return {"agent": "quality", "verdict": "pass"}

    for agent in (FailAll(), IncompletePass()):
        decision = MakeDecision(load_scenario(BASELINE), quality=agent).decide(budget=BUDGET)
        assert decision["status"] == REFUSE
        assert decision["selected_plan"] is None


def test_the_restrictions_are_named_not_anonymous():
    loop = rounds_of(decide(NO_FEASIBLE))
    assert any("отбор" in r or "запас" in r or "качество" in r for r in loop[0]["restriction_added"])


def test_each_round_records_which_agent_vetoed():
    loop = rounds_of(decide(NO_FEASIBLE))
    assert "quality_vetoed" in loop[0] and "reliability_vetoed" in loop[0]
    assert loop[0]["quality_vetoed"] + loop[0]["reliability_vetoed"] > 0


def test_the_loop_is_bounded_and_terminates():
    decision = decide(NO_FEASIBLE)
    loop = rounds_of(decision)
    assert len(loop) <= MAX_ROUNDS
    assert decision["status"] == REFUSE


def test_the_loop_stops_when_further_restriction_would_change_nothing():
    loop = rounds_of(decide(NO_FEASIBLE))
    assert loop[-1].get("restriction_added") == [] or loop[-1].get("note")


def test_a_feasible_first_round_does_not_trigger_extra_rounds():
    assert len(rounds_of(decide(BASELINE))) == 1



def test_the_quality_agent_reports_only_quality_checks():
    planner = orchestrator(SOUR).planner
    plans, _ = planner.build_plans(BUDGET)
    review = QualityReview().review(planner.evaluate(plans[0]))
    assert review["agent"] == "quality"
    assert set(review) >= {"vetoes", "unknown", "verdict"}


def test_the_reliability_agent_reports_equipment_limits_and_severity():
    planner = orchestrator(SOUR).planner
    plans, _ = planner.build_plans(BUDGET)
    review = ReliabilityReview().review(planner.evaluate(plans[0]))
    assert review["agent"] == "reliability"
    assert "severity_index" in review
    assert "не оценка реального ресурса" in review["scope"]


def test_the_final_plan_is_reviewed_again_by_both_agents():
    trace = decide(SOUR)["trace"]
    final = [t for t in trace if t.get("stage") == "final"]
    assert {t["agent"] for t in final} == {"quality", "reliability"}



def test_all_candidates_failing_computation_is_reported_as_computation_error_not_no_feasible_plan():
    o = orchestrator(SOUR)

    def always_broken(plan, confirmed=(), initial_tanks=None, current_operation=None):
        raise ValueError("расчёт кандидата сломан")

    o.planner.evaluate = always_broken
    decision = o.decide(budget=BUDGET)
    assert decision["status"] == REFUSE
    assert decision["refusal"]["kind"] == "computation_error"
    assert decision["refusal"]["examples"]
    assert "расчёт кандидата сломан" in decision["refusal"]["examples"][0]


def test_partial_computation_failures_do_not_block_a_normal_decision():
    o = orchestrator(SOUR)
    original = o.planner.evaluate
    calls = {"n": 0}

    def fail_first_then_ok(plan, confirmed=(), initial_tanks=None, current_operation=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("первый кандидат сломан")
        return original(plan, confirmed=confirmed, initial_tanks=initial_tanks,
                        current_operation=current_operation)

    o.planner.evaluate = fail_first_then_ok
    decision = o.decide(budget=BUDGET)
    assert decision["status"] != REFUSE or decision.get("refusal", {}).get("kind") != "computation_error"


def test_an_optimizer_failure_raises_instead_of_returning_a_decision():
    o = orchestrator()

    def broken(budget):
        raise ValueError("сломано")

    o.planner.build_plans = broken
    with pytest.raises(AgentError, match="не смог построить"):
        o.decide(budget=BUDGET)


def test_a_plan_failing_the_final_recheck_is_refused_not_released():
    o = orchestrator(SOUR)
    original = o.planner.evaluate
    calls = {"n": 0}

    def sometimes_failing(plan, confirmed=()):
        evaluation = original(plan, confirmed)
        calls["n"] += 1
        return evaluation

    o.planner.evaluate = sometimes_failing
    decision = o.decide(budget=BUDGET)
    assert decision["status"] in (HOLD, RECOMMEND_SCENARIO)
    assert decision["gate"]["feasible"] is True, "выпущенный план обязан заново пройти gate"


def test_a_released_plan_always_carries_a_passing_gate():
    for path in (BASELINE, SOUR):
        decision = decide(path)
        assert decision["gate"]["feasible"] is True


def test_a_refusal_never_carries_a_gate_verdict_of_its_own():
    assert decide(NO_FEASIBLE)["gate"] is None



def test_every_decision_has_a_stable_identifier():
    first, second = decide(BASELINE), decide(BASELINE)
    assert first["decision_id"] == second["decision_id"]
    assert len(first["decision_id"]) == 16


def test_different_scenarios_give_different_decisions():
    assert decide(BASELINE)["decision_id"] != decide(SOUR)["decision_id"]


def test_the_trace_shows_the_whole_cycle_in_order():
    trace = decide(SOUR, state=healthy_state())["trace"]
    agents = [t["agent"] for t in trace]
    assert agents[0] == "data"
    assert "optimizer" in agents
    assert agents.index("optimizer") < agents.index("quality")


def test_the_result_states_its_scope():
    decision = decide(BASELINE)
    assert "не считается исполненным" in decision["note"]
    assert decision["scope"] == "synthetic_scenario"


def test_search_respects_one_budget_and_deduplicates_content():
    engine = MakeDecision(load_scenario(NO_FEASIBLE))
    seen = []
    evaluate = engine.planner.evaluate
    def recording(plan, confirmed=()):
        seen.append(json.dumps([step.to_dict() for step in plan.steps], sort_keys=True))
        return evaluate(plan, confirmed)
    engine.planner.evaluate = recording
    result = engine.decide(budget=40)
    assert result["status"] == REFUSE
    assert len(seen) <= 40
    assert len(seen) == len(set(seen))


def test_budget_sampling_does_not_drop_all_transition_plans():
    engine = MakeDecision(load_scenario(BASELINE))
    plans, _ = engine.planner.build_plans(600)
    sampled = engine._sample_plans(plans, 200)
    assert sampled[0].plan_id == "hold"
    assert len(sampled) == 200
    assert any(len(p.steps) == 2 for p in sampled)
