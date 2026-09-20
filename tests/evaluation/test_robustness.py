import copy
import json
from pathlib import Path

import pytest

from neftecode.application.use_cases.make_decision import MakeDecision
from neftecode.application.use_cases.plan_operation import PlanOperation
from neftecode.evaluation.robustness import (DEFAULT_PERTURBATIONS, RobustnessCheck,
                                             COMBINED_RESPONSE_STRESS, RobustnessError, choose_robust, perturb)
from neftecode.infrastructure.config.scenario import load_scenario, parse_scenario

BASELINE = Path("config/scenarios/baseline.json")
SOUR = Path("config/scenarios/sour_crude.json")
BUDGET = 400


def raw(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def chosen_plan(path):
    scenario = load_scenario(path)
    decision = MakeDecision(scenario).decide(budget=BUDGET)
    plans, _ = PlanOperation(scenario).build_plans(BUDGET)
    plan = next(p for p in plans if p.plan_id == decision["selected_plan"]["plan_id"])
    return scenario, plan


def checker(scenario, document, perturbations=DEFAULT_PERTURBATIONS):
    return RobustnessCheck(
        scenario, document, perturbations, scenario_parser=parse_scenario
    )



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
    altered = perturb(raw(BASELINE), {"name": "x", "path": "tank.main.inventory", "factor": 0.5})
    main = next(t for t in altered["tanks"] if t["tank_id"] == "main")
    assert main["inventory"]["value"] == pytest.approx(2000.0)


def test_the_supply_limit_of_an_on_demand_component_can_be_perturbed():
    altered = perturb(raw(BASELINE), {"name": "x", "path": "tank.reserve.max_outflow", "factor": 0.5})
    reserve = next(t for t in altered["tanks"] if t["tank_id"] == "reserve")
    assert reserve["max_outflow"]["value"] == pytest.approx(15.0)
    parse_scenario(altered)


def test_perturbing_a_stock_of_a_component_that_has_none_is_refused():
    with pytest.raises(RobustnessError, match="нет поля inventory"):
        perturb(raw(BASELINE), {"name": "x", "path": "tank.reserve.inventory", "factor": 0.5})


def test_the_perturbed_lag_stays_inside_the_case_bounds():
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



def test_a_plan_that_breaks_under_an_allowed_deviation_is_called_fragile():
    scenario, plan = chosen_plan(SOUR)
    check = checker(scenario, raw(SOUR)).run(plan)
    assert check["violated"] > 0, "нужен пример плана, теряющего допустимость при отклонении"
    assert check["fragile"] is True
    assert ("рекомендация блокируется" in check["verdict"]
            if check["mandatory_failed"] else "как надёжный не выдаётся" in check["verdict"])


def test_the_broken_perturbations_are_named_with_their_first_violation():
    scenario, plan = chosen_plan(SOUR)
    check = checker(scenario, raw(SOUR)).run(plan)
    broken = [r for r in check["results"] if r["outcome"] == "violated"]
    assert broken
    for result in broken:
        assert result["perturbation"]
        assert result["first_violation"]["reason"]


def test_a_fragile_plan_is_released_only_when_failures_are_diagnostic():
    scenario = load_scenario(SOUR)
    document = raw(SOUR)
    diagnostic = tuple({k: v for k, v in p.items() if k != "mandatory"}
                       for p in DEFAULT_PERTURBATIONS
                       if p["path"] != "hydrotreating.response_stress")
    decision = MakeDecision(scenario, robustness_evaluator=checker(
        scenario, document, diagnostic)).decide(
        budget=BUDGET, raw_scenario=document)
    assert decision["robustness"]["fragile"] is True
    assert "надёжным не считается" in decision["reason"]


def test_a_robust_plan_carries_no_such_warning():
    scenario = load_scenario(BASELINE)
    document = raw(BASELINE)
    decision = MakeDecision(scenario, robustness_evaluator=checker(scenario, document)).decide(
        budget=BUDGET, raw_scenario=document)
    assert decision["robustness"]["fragile"] is False
    assert "надёжным не считается" not in decision["reason"]


def test_a_robust_plan_holds_every_declared_perturbation():
    scenario, plan = chosen_plan(BASELINE)
    check = checker(scenario, raw(BASELINE)).run(plan)
    assert check["held"] == check["perturbations_evaluated"]
    assert check["share_holding"] == pytest.approx(1.0)



def test_the_perturbation_set_is_recorded_with_the_result():
    scenario, plan = chosen_plan(SOUR)
    check = checker(scenario, raw(SOUR)).run(plan)
    assert check["perturbations_declared"] == len(DEFAULT_PERTURBATIONS)
    assert len(check["results"]) == len(DEFAULT_PERTURBATIONS)
    assert all(r["perturbation"] for r in check["results"])


def test_the_share_is_never_presented_as_a_probability():
    scenario, plan = chosen_plan(SOUR)
    limits = checker(scenario, raw(SOUR)).run(plan)["limits"]
    assert any("не вероятность успеха" in limit for limit in limits)
    assert any("не доверительный интервал" in limit for limit in limits)


def test_the_shared_model_limitation_is_stated():
    scenario, plan = chosen_plan(SOUR)
    limits = checker(scenario, raw(SOUR)).run(plan)["limits"]
    assert any("той же модели отклика" in limit for limit in limits)


def test_a_long_episode_is_not_declared_a_new_regime():
    scenario, plan = chosen_plan(SOUR)
    limits = checker(scenario, raw(SOUR)).run(plan)["limits"]
    assert any("новым режимом не признаётся" in limit for limit in limits)


def test_a_custom_perturbation_set_is_honoured():
    scenario, plan = chosen_plan(BASELINE)
    single = ({"name": "только сера сырья", "path": "crude.sulfur_wt_pct", "factor": 1.05},)
    check = checker(scenario, raw(BASELINE), single).run(plan)
    assert check["perturbations_declared"] == 1
    assert check["results"][0]["perturbation"] == "только сера сырья"


def test_combined_response_stress_can_be_enabled_explicitly():
    scenario, _, warmer, _ = _hold_and_moves(BASELINE)
    check = checker(scenario, raw(BASELINE), (COMBINED_RESPONSE_STRESS,)).run(warmer)
    assert check["perturbations_declared"] == 1
    assert check["perturbations_evaluated"] == 1
    assert check["results"][0]["path"] == "hydrotreating.response_stress"
    assert check["results"][0]["mandatory"] is True


def test_mandatory_response_stress_is_part_of_the_shipped_check():
    shipped = [item for item in DEFAULT_PERTURBATIONS
               if item["path"] == COMBINED_RESPONSE_STRESS["path"]]
    assert shipped == [COMBINED_RESPONSE_STRESS]
    assert shipped[0]["mandatory"] is True


def test_the_shipped_combined_stress_is_mandatory_without_scenario_policy():
    """Обязательность не зависит от того, перечислил ли сценарий путь в policy."""
    scenario, _, warmer, _ = _hold_and_moves(BASELINE)
    document = raw(BASELINE)
    assert not (document.get("policy") or {}).get("mandatory_robustness_paths")
    check = checker(scenario, document).run(warmer)
    combined = [r for r in check["results"] if r["path"] == COMBINED_RESPONSE_STRESS["path"]]
    assert len(combined) == 1 and combined[0]["mandatory"] is True
    assert check["mandatory_declared"] >= 1


def test_a_plan_failing_a_mandatory_range_is_replanned_before_release():
    document = raw(SOUR)
    document["policy"].pop("severity_cost_tolerance_fraction", None)
    scenario = parse_scenario(document)
    unguarded = MakeDecision(scenario).decide(budget=BUDGET)
    decision = MakeDecision(
        scenario,
        robustness_evaluator=checker(scenario, document),
        scenario_parser=parse_scenario,
    ).decide(budget=BUDGET, raw_scenario=document)
    assert decision["status"] != "refuse"
    assert decision["selected_plan"]["plan_id"] != unguarded["selected_plan"]["plan_id"]
    assert decision["robustness"]["mandatory_failed"] == 0
    robustness_steps = [entry for entry in decision["trace"] if entry.get("agent") == "robustness"]
    assert any(entry["mandatory_failed"] > 0 for entry in robustness_steps[:-1])


def test_the_check_is_reproducible():
    scenario, plan = chosen_plan(SOUR)
    evaluator = checker(scenario, raw(SOUR))
    assert evaluator.run(plan) == evaluator.run(plan)



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



def _hold_and_moves(path):
    scenario = load_scenario(path)
    plans, _ = PlanOperation(scenario).build_plans(BUDGET)
    base = PlanOperation(scenario).base_controls()
    hold = next(p for p in plans if p.plan_id == "hold")
    warmer = next(p for p in plans if len(p.steps) == 1 and p.steps[0].additive_dose == 0
                  and p.steps[0].controls["ht_reactor_inlet_temp_c"] > base["ht_reactor_inlet_temp_c"] + 0.5)
    blend_only = next(p for p in plans if len(p.steps) == 1 and p.plan_id != "hold"
                      and all(abs(p.steps[0].controls[k] - v) < 1e-9 for k, v in base.items()))
    return scenario, hold, warmer, blend_only


def test_response_and_lag_perturbations_do_not_count_for_a_hold():
    scenario, hold, _, blend_only = _hold_and_moves(BASELINE)
    for plan in (hold, blend_only):
        check = checker(scenario, raw(BASELINE)).run(plan)
        skipped = {r["perturbation"]: r for r in check["results"] if r["outcome"] == "not_applicable"}
        assert set(skipped) == {"отклик ГО слабее на 20%", "запаздывание отклика +50%",
                                "слабый отклик ГО и задержка +50% одновременно"}
        assert all("не действует" in r["reason"] for r in skipped.values())
        assert check["not_applicable"] == 3
        assert check["perturbations_declared"] == len(DEFAULT_PERTURBATIONS)
        assert check["perturbations_evaluated"] == len(DEFAULT_PERTURBATIONS) - 3
        assert check["held"] + check["violated"] == check["perturbations_evaluated"]
        assert check["share_holding"] == pytest.approx(check["held"] / check["perturbations_evaluated"])
    assert any("неприменимо" in limit for limit in check["limits"])


def test_a_temperature_move_is_still_checked_against_response_and_lag():
    scenario, _, warmer, _ = _hold_and_moves(BASELINE)
    check = checker(scenario, raw(BASELINE)).run(warmer)
    assert check["not_applicable"] == 0
    assert check["perturbations_evaluated"] == len(DEFAULT_PERTURBATIONS)


def test_a_confirmed_temperature_move_makes_the_perturbations_applicable_to_a_hold():
    scenario, hold, _, _ = _hold_and_moves(BASELINE)
    base = PlanOperation(scenario).base_controls()["ht_reactor_inlet_temp_c"]
    check = checker(scenario, raw(BASELINE)).run(hold, confirmed=((-1.0, {"ht_reactor_inlet_temp_c": base + 1.0}),))
    assert check["not_applicable"] == 0


def test_data_driven_edges_are_inapplicable_to_a_hold_on_a_bound_scenario():
    from neftecode.infrastructure.live.advisor import bind_forecast, bind_measurements
    document = raw(BASELINE)
    response = {"schema_version": "v1", "tag": "ht.T6", "flow_tag": "ht.F9", "tau": "2026-01-01", "window_months": 12,
                "beta_mgkg_per_c": -0.4332, "ci": [-0.4761, -0.397], "envelope_dt_c": 2.0, "n_rows": 1, "method": "тест",
                "drift": [], "flow_beta": None, "model_fingerprint": "x", "t6_range_c": [342.9, 386.1],
                "f9_range_tph": [150.3, 256.7], "weak_strong": [-0.217, -0.739]}
    measured = {tag: {"value": value, "time": "2026-01-05T08:00:00", "age_min": 0.0, "max_age_min": 30.0}
                for tag, value in (("ht.T6", 367.8), ("ht.F9", 206.1), ("ht.F26", 244.1))}
    forecast = {"model": "last_pak", "value": 6.0, "lower": 4.0, "upper": 9.0, "available": True, "reason": "тест"}
    bound = bind_forecast(bind_measurements(document, measured, {"density_kgm3": 836.1}, response, forecast), forecast)
    scenario = parse_scenario(bound)
    hold = next(p for p in PlanOperation(scenario).build_plans(BUDGET)[0] if p.plan_id == "hold")
    check = checker(scenario, bound).run(hold)
    assert check["perturbations_declared"] == len(DEFAULT_PERTURBATIONS) + 2
    assert check["not_applicable"] == 5
    assert check["perturbations_evaluated"] == len(DEFAULT_PERTURBATIONS) - 3
