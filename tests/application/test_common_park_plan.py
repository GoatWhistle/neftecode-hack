import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest

from neftecode.application.services.robustness import RobustnessCheck
from neftecode.application.services.tank_estimate import default_tank_estimate_factory
from neftecode.application.use_cases.make_decision import MakeDecision
from neftecode.domain.advisory.optimizer import rank
from neftecode.infrastructure.config.scenario import parse_scenario


@pytest.fixture
def raw():
    document = json.loads(Path("config/scenarios/sour_crude.json").read_text())
    document["measurement_binding"] = {"tags": {}}
    main = document["tanks"][0]
    main["properties"]["sulfur_mgkg"]["value"] = 7.8822
    main["sulfur_from_chain"] = False
    main["inflow_sulfur_mgkg"] = {"value": 20.9422, "unit": "мг/кг", "source": "scenario"}
    main["inflow"]["value"] = 227.787
    return document


def maker_for(raw, **kwargs):
    return MakeDecision(parse_scenario(raw), scenario_parser=parse_scenario,
                        tank_estimate_factory=default_tank_estimate_factory, **kwargs)


def test_different_phase_optima_yield_a_common_plan_with_explicit_cost(raw):
    before = copy.deepcopy(raw)
    maker = maker_for(raw, robustness_evaluator=RobustnessCheck(
        parse_scenario(raw), raw, scenario_parser=parse_scenario))
    decision = maker.decide(budget=400, raw_scenario=raw)
    assert decision["status"] == "recommend_scenario"
    assert decision["production_t"] == 150
    assert decision["immediate_action"]["throughput_tph"] == 50
    assert decision["gate"]["feasible"] is True
    report = decision["tank_estimate"]
    assert report["baseline_plan"] == "hold"
    assert report["selection_changed"] is True
    assert report["common_candidates"] > 0
    assert report["same"] == 3 and not report["sensitive"]
    assert report["coverage"]["complete"] is True
    assert report["coverage"]["method"] == "continuous_interval_bounds"
    assert report["coverage"]["tau_domain_h"]["upper_inclusive"] is False
    assert {r["plan_id"] for r in report["results"]} == {decision["selected_plan"]["plan_id"]}
    assert all(r["feasible"] and not r["reasons"] for r in report["results"])
    assert report["compromise"]["production_loss_t"] == 150
    hold = next(p for p in maker.build_plans(400)[0] if p.plan_id == "hold")
    assert report["compromise"]["cost_per_tonne_delta"] == pytest.approx(
        decision["cost_per_tonne"] - maker.evaluate_plan(hold).cost_per_tonne)
    assert "300 → 150 т" in decision["reason"]
    assert "исходной модельной фазе" in report["compromise"]["basis"]
    assert decision["commercial_release_allowed"] is False
    assert raw == before
    excluded = {r["plan_id"] for r in report["excluded_candidates"]}
    assert "hold" in excluded
    assert all(p["candidate_id"] != "hold" for p in decision["alternatives"])
    hold_card = next(c for c in decision["choice"]["candidates"] if c["candidate_id"] == "hold")
    assert hold_card["verdict"] == "excluded"
    assert any(r["stage"] == "park_phase" for r in hold_card["reasons"])
    assert any(r["stage"] == "park_phase" for r in decision["choice"]["determined_by"])


def test_restricted_pool_does_not_resurrect_safe_plans_excluded_by_agents(raw):
    maker = maker_for(raw)
    plans, _ = maker.build_plans(400)
    hold = next(p for p in plans if p.plan_id == "hold")
    evaluation = maker.evaluate_plan(hold)
    assert evaluation.feasible
    decision = maker.release(rank([evaluation]), hold, [evaluation], {"hold": hold}, [],
                             budget=400, raw_scenario=raw)
    assert decision["status"] == "refuse"
    assert decision["refusal"]["kind"] == "tank_phase_sensitive"
    assert decision["selected_plan"] is None
    assert decision["tank_estimate"]["common_candidates"] == 0
    assert decision["tank_estimate"]["failed_taus_h"]
    assert "Среди рассмотренных планов" in decision["reason"]


def test_phase_check_uses_plan_contents_not_its_identifier(raw):
    maker = maker_for(raw)
    plans, _ = maker.build_plans(400)
    hold = next(p for p in plans if p.plan_id == "hold")
    impostor = replace(hold, plan_id="c0001")
    evaluation = maker.evaluate_plan(impostor)
    decision = maker.release(rank([evaluation]), impostor, [evaluation], {"c0001": impostor}, [],
                             raw_scenario=raw, budget=400)
    assert decision["status"] == "refuse"
    assert decision["tank_estimate"]["common_candidates"] == 0


def test_unknown_phase_blocks_recommendation(raw):
    maker = maker_for(raw)

    def unavailable(document):
        if document["tank_park"]["phase_offsets_h"][0] == 0:
            raise ValueError("Стадия не вычисляется")
        return parse_scenario(document)

    maker.scenario_parser = unavailable
    decision = maker.decide(budget=100, raw_scenario=raw)
    assert decision["status"] == "refuse"
    assert decision["selected_plan"] is None
    assert decision["tank_estimate"]["available"] is False
    assert "Стадия не вычисляется" in decision["reason"]
    assert 0 in decision["tank_estimate"]["failed_taus_h"]
    assert decision["tank_estimate"]["errors"]


def test_mandatory_robustness_is_checked_in_each_phase(raw):
    checked = []

    class PhaseStress:
        def evaluate(self, scenario, phase_raw, plan, *args):
            tau = phase_raw["tank_park"]["phase_offsets_h"][0]
            checked.append(tau)
            return {"mandatory_failed": int(tau == 0), "mandatory_failure_names": ["стресс в начале налива"]}

    maker = maker_for(raw, robustness_evaluator=PhaseStress())
    plan = next(p for p in maker.build_plans(400)[0] if p.plan_id == "c0001")
    evaluation = maker.evaluate_plan(plan)
    decision = maker.release(rank([evaluation]), plan, [evaluation], {plan.plan_id: plan}, [],
                             raw_scenario=raw, budget=400)
    assert decision["status"] == "refuse"
    assert decision["tank_estimate"]["common_candidates"] == 0
    assert 0 in checked and len(set(checked)) == 3
    assert any("стресс в начале налива" in r["reasons"]
               for item in decision["tank_estimate"]["excluded_candidates"] for r in item["failed_phases"])


def test_phase_review_veto_is_not_lost(raw):
    class RefuseReview:
        def review(self, evaluation):
            return {"agent": "quality", "checked": 1, "passed": 0, "vetoes": ["запрет эксперта"],
                    "unknown": [], "verdict": "fail"}

    maker = maker_for(raw)
    plans, _ = maker.build_plans(400)
    plan = next(p for p in plans if p.plan_id == "c0001")
    evaluation = maker.evaluate_plan(plan)
    assert evaluation.feasible
    maker.quality = RefuseReview()
    decision = maker.release(rank([evaluation]), plan, [evaluation], {plan.plan_id: plan}, [],
                             raw_scenario=raw, budget=400)
    assert decision["status"] == "refuse"
    assert decision["tank_estimate"]["common_candidates"] == 0


def test_candidate_error_excludes_only_unverified_plan(raw, monkeypatch):
    maker = maker_for(raw)
    plan = next(p for p in maker.build_plans(400)[0] if p.plan_id == "c0001")
    alternative = replace(plan, plan_id="same_action")
    evaluations = [maker.evaluate_plan(p) for p in (plan, alternative)]
    original = MakeDecision._evaluate_plan

    def failing(self, candidate, *args):
        if candidate.plan_id == "c0001" and self.scenario.tank_park.phase_offsets_h[0] == 0:
            raise ValueError("Сбой расчёта кандидата")
        return original(self, candidate, *args)

    monkeypatch.setattr(MakeDecision, "_evaluate_plan", failing)
    decision = maker.release(rank(evaluations), plan, evaluations,
                             {p.plan_id: p for p in (plan, alternative)}, [], raw_scenario=raw)
    assert decision["status"] == "recommend_scenario"
    assert decision["selected_plan"]["plan_id"] == "same_action"
    assert decision["tank_estimate"]["available"] is True
    assert decision["tank_estimate"]["same"] == 3
    excluded = decision["tank_estimate"]["excluded_candidates"]
    assert excluded[0]["plan_id"] == "c0001"
    assert excluded[0]["failed_phases"][0]["outcome"] == "not_evaluable"


def test_weak_response_failure_in_one_phase_blocks_the_plan(raw, monkeypatch):
    maker = maker_for(raw)
    plan = next(p for p in maker.build_plans(400)[0] if p.plan_id == "c0001")
    evaluation = maker.evaluate_plan(plan)

    def guard(self, *args):
        if self.scenario.tank_park.phase_offsets_h[0] == 0:
            return {"outcome": "violated", "violations": ["слабый отклик в начале налива"]}
        return {"outcome": "holds"}

    monkeypatch.setattr(MakeDecision, "_weak_response_guard", guard)
    decision = maker.release(rank([evaluation]), plan, [evaluation], {plan.plan_id: plan}, [],
                             raw_scenario=raw)
    assert decision["status"] == "refuse"
    assert decision["tank_estimate"]["common_candidates"] == 0
    assert "слабый отклик в начале налива" in decision["tank_estimate"]["results"][0]["reasons"]


def test_three_successes_cannot_bypass_missing_continuous_stress_check(raw):
    class UncertifiedStress:
        def evaluate(self, *args):
            return {"mandatory_failed": 0}

    maker = maker_for(raw, robustness_evaluator=UncertifiedStress())
    plan = next(p for p in maker.build_plans(400)[0] if p.plan_id == "c0001")
    evaluation = maker.evaluate_plan(plan)
    decision = maker.release(rank([evaluation]), plan, [evaluation], {plan.plan_id: plan}, [], raw_scenario=raw)
    assert decision["status"] == "refuse"
    assert decision["tank_estimate"]["same"] == 3
    assert decision["tank_estimate"]["coverage"]["complete"] is False
    assert "стрессы" in decision["reason"]


def test_mandatory_perturbation_is_part_of_continuous_certificate(raw):
    raw["policy"]["mandatory_robustness_paths"] = ["tank.reserve.max_outflow"]
    maker = maker_for(raw, robustness_evaluator=RobustnessCheck(
        parse_scenario(raw), raw, scenario_parser=parse_scenario))
    plan = next(p for p in maker.build_plans(400)[0] if p.plan_id == "c0001")
    proof = maker._phase_certificate(plan, raw, (), None, None)
    assert any(c["name"] == "подача резерва -20%" for c in proof["stress_checks"])
    assert all(c["method"] == "continuous_interval_bounds" for c in proof["stress_checks"])


def test_standalone_phase_api_also_covers_mandatory_stress(raw):
    raw["policy"]["mandatory_robustness_paths"] = ["tank.main.sulfur_mgkg"]
    check = default_tank_estimate_factory(parse_scenario(raw), raw, parse_scenario)
    report = check.evaluate("recommend_scenario", "c0001", budget=400)
    assert report["coverage"]["complete"] is True
    assert any(c["name"] == "сера основного компонента +10%" for c in report["coverage"]["stress_checks"])
    assert not report["sensitive"]
