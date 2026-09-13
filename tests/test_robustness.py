"""A nominally good plan that breaks under an allowed deviation is not released as reliable."""
import copy
import json
from pathlib import Path

import pytest

from neftecode.application.use_cases.make_decision import MakeDecision
from neftecode.application.use_cases.plan_operation import PlanOperation
from neftecode.robustness import (DEFAULT_PERTURBATIONS, RobustnessCheck, RobustnessError,
                                  choose_robust, perturb)
from neftecode.infrastructure.config.scenario import load_scenario, parse_scenario

BASELINE = Path("config/scenarios/baseline.json")
SOUR = Path("config/scenarios/sour_crude.json")
BUDGET = 400


def raw(path):
    return json.loads(Path(path).read_text())


def chosen_plan(path):
    scenario = load_scenario(path)
    decision = MakeDecision(scenario).decide(budget=BUDGET)
    plans, _ = PlanOperation(scenario).build_plans(BUDGET)
    plan = next(p for p in plans if p.plan_id == decision["selected_plan"]["plan_id"])
    return scenario, plan


# --- Perturbations are named, reproducible edits ---

def test_a_perturbation_changes_only_what_it_names():
    original = raw(BASELINE)
    altered = perturb(original, {"name": "x", "path": "crude.sulfur_wt_pct", "factor": 1.1})
    assert altered["crude"]["sulfur_wt_pct"]["value"] == pytest.approx(
        original["crude"]["sulfur_wt_pct"]["value"] * 1.1)
    assert altered["tanks"] == original["tanks"]


def test_the_original_scenario_is_not_mutated():
    original = raw(BASELINE)
    before = copy.deepcopy(original)
    perturb(original, {"name": "x", "path": "crude.sulfur_wt_pct", "factor": 2.0})
    assert original == before


def test_a_tank_property_can_be_perturbed():
    altered = perturb(raw(BASELINE), {"name": "x", "path": "tank.reserve.sulfur_mgkg", "factor": 1.5})
    reserve = next(t for t in altered["tanks"] if t["tank_id"] == "reserve")
    assert reserve["properties"]["sulfur_mgkg"]["value"] == pytest.approx(3.0)


def test_a_tank_stock_can_be_perturbed():
    altered = perturb(raw(BASELINE), {"name": "x", "path": "tank.reserve.inventory", "factor": 0.5})
    reserve = next(t for t in altered["tanks"] if t["tank_id"] == "reserve")
    assert reserve["inventory"]["value"] == pytest.approx(300.0)


def test_the_perturbed_lag_stays_inside_the_case_bounds():
    """A perturbation may not push the response lag outside the 0-3 hour range of the case."""
    altered = perturb(raw(BASELINE),
                      {"name": "x", "path": "hydrotreating.response_lag_hours", "factor": 10.0})
    assert altered["stages"]["hydrotreating"]["response_lag_hours"]["value"] <= 3.0
    parse_scenario(altered)


def test_an_unknown_path_is_refused():
    with pytest.raises(RobustnessError, match="неизвестный путь"):
        perturb(raw(BASELINE), {"name": "x", "path": "погода.дождь", "factor": 1.1})


def test_a_missing_tank_is_refused():
    with pytest.raises(RobustnessError, match="не описан"):
        perturb(raw(BASELINE), {"name": "x", "path": "tank.ghost.sulfur_mgkg", "factor": 1.1})


def test_perturbing_an_unknown_property_is_refused():
    with pytest.raises(RobustnessError, match="нет свойства"):
        perturb(raw(BASELINE), {"name": "x", "path": "tank.light.cetane_number", "factor": 1.1})


@pytest.mark.parametrize("factor", [0, -1, float("nan")])
def test_an_impossible_factor_is_refused(factor):
    with pytest.raises(RobustnessError, match="множитель"):
        perturb(raw(BASELINE), {"name": "x", "path": "crude.sulfur_wt_pct", "factor": factor})


def test_every_default_perturbation_applies_to_the_shipped_scenarios():
    for path in (BASELINE, SOUR):
        for spec in DEFAULT_PERTURBATIONS:
            parse_scenario(perturb(raw(path), spec))


# --- The required example: a nominally good plan that breaks ---

def test_a_plan_that_breaks_under_an_allowed_deviation_is_called_fragile():
    scenario, plan = chosen_plan(SOUR)
    check = RobustnessCheck(scenario, raw(SOUR)).run(plan)
    assert check["violated"] > 0, "нужен пример плана, теряющего допустимость при отклонении"
    assert check["fragile"] is True
    assert "как надёжный не выдаётся" in check["verdict"]


def test_the_broken_perturbations_are_named_with_their_first_violation():
    scenario, plan = chosen_plan(SOUR)
    check = RobustnessCheck(scenario, raw(SOUR)).run(plan)
    broken = [r for r in check["results"] if r["outcome"] == "violated"]
    assert broken
    for result in broken:
        assert result["perturbation"]
        assert result["first_violation"]["reason"]


def test_a_fragile_plan_is_released_with_a_warning_not_as_reliable():
    scenario = load_scenario(SOUR)
    document = raw(SOUR)
    decision = MakeDecision(scenario, robustness_evaluator=RobustnessCheck(scenario, document)).decide(
        budget=BUDGET, raw_scenario=document)
    assert decision["robustness"]["fragile"] is True
    assert "надёжным не считается" in decision["reason"]


def test_a_robust_plan_carries_no_such_warning():
    scenario = load_scenario(BASELINE)
    document = raw(BASELINE)
    decision = MakeDecision(scenario, robustness_evaluator=RobustnessCheck(scenario, document)).decide(
        budget=BUDGET, raw_scenario=document)
    assert decision["robustness"]["fragile"] is False
    assert "надёжным не считается" not in decision["reason"]


def test_a_robust_plan_holds_every_declared_perturbation():
    scenario, plan = chosen_plan(BASELINE)
    check = RobustnessCheck(scenario, raw(BASELINE)).run(plan)
    assert check["held"] == check["perturbations_evaluated"]
    assert check["share_holding"] == pytest.approx(1.0)


# --- The set of perturbations and its limits are kept ---

def test_the_perturbation_set_is_recorded_with_the_result():
    scenario, plan = chosen_plan(SOUR)
    check = RobustnessCheck(scenario, raw(SOUR)).run(plan)
    assert check["perturbations_declared"] == len(DEFAULT_PERTURBATIONS)
    assert len(check["results"]) == len(DEFAULT_PERTURBATIONS)
    assert all(r["perturbation"] for r in check["results"])


def test_the_share_is_never_presented_as_a_probability():
    scenario, plan = chosen_plan(SOUR)
    limits = RobustnessCheck(scenario, raw(SOUR)).run(plan)["limits"]
    assert any("не вероятность успеха" in limit for limit in limits)
    assert any("не доверительный интервал" in limit for limit in limits)


def test_the_shared_model_limitation_is_stated():
    scenario, plan = chosen_plan(SOUR)
    limits = RobustnessCheck(scenario, raw(SOUR)).run(plan)["limits"]
    assert any("той же модели отклика" in limit for limit in limits)


def test_a_long_episode_is_not_declared_a_new_regime():
    scenario, plan = chosen_plan(SOUR)
    limits = RobustnessCheck(scenario, raw(SOUR)).run(plan)["limits"]
    assert any("новым режимом не признаётся" in limit for limit in limits)


def test_a_custom_perturbation_set_is_honoured():
    scenario, plan = chosen_plan(BASELINE)
    single = ({"name": "только сера сырья", "path": "crude.sulfur_wt_pct", "factor": 1.05},)
    check = RobustnessCheck(scenario, raw(BASELINE), single).run(plan)
    assert check["perturbations_declared"] == 1
    assert check["results"][0]["perturbation"] == "только сера сырья"


def test_the_check_is_reproducible():
    scenario, plan = chosen_plan(SOUR)
    checker = RobustnessCheck(scenario, raw(SOUR))
    assert checker.run(plan) == checker.run(plan)


# --- Choosing a more robust plan ---

def test_a_robust_plan_is_preferred_over_a_fragile_one():
    scenario = load_scenario(BASELINE)
    planner = PlanOperation(scenario)
    plans, _ = planner.build_plans(BUDGET)
    evaluations = [planner.evaluate(p) for p in plans[:12]]
    feasible = [e for e in evaluations if e.feasible]
    assert len(feasible) >= 2
    best = min(feasible, key=lambda e: e.key())
    other = next(e for e in feasible if e is not best)
    checks = {best.candidate.candidate_id: {"fragile": True},
              other.candidate.candidate_id: {"fragile": False}}
    choice = choose_robust(feasible, checks)
    assert choice["selected"] == other.candidate.candidate_id
    assert "сохраняющий допустимость" in choice["reason"]


def test_when_every_plan_is_fragile_the_result_says_so():
    scenario = load_scenario(BASELINE)
    planner = PlanOperation(scenario)
    plans, _ = planner.build_plans(BUDGET)
    evaluations = [e for e in (planner.evaluate(p) for p in plans[:12]) if e.feasible]
    checks = {e.candidate.candidate_id: {"fragile": True} for e in evaluations}
    choice = choose_robust(evaluations, checks)
    assert choice["fragile"] is True
    assert "не как надёжный" in choice["reason"]


def test_without_feasible_plans_nothing_is_chosen():
    assert choose_robust([], {})["selected"] is None
