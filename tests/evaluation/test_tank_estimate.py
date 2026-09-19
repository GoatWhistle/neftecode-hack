import copy
import json
from pathlib import Path

import pytest

from neftecode.application.services.risk_block import risk_block
from neftecode.application.use_cases.make_decision import MakeDecision
from neftecode.evaluation.robustness import RobustnessCheck
from neftecode.evaluation.tank_estimate import (INVENTORY_RELATIVE, SULFUR_ABSOLUTE_MGKG, TankEstimateCheck,
                                                TankEstimateError, apply, estimate_provenance, perturbations,
                                                plain_decision)
from neftecode.infrastructure.config.scenario import load_scenario, parse_scenario

BASELINE = Path("config/scenarios/baseline.json")
SOUR = Path("config/scenarios/sour_crude.json")
BUDGET = 400


def raw(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def decide(path: Path) -> dict:
    document = raw(path)
    scenario = load_scenario(path)
    return MakeDecision(scenario, robustness_evaluator=RobustnessCheck(
        scenario, document, scenario_parser=parse_scenario)).decide(budget=BUDGET, raw_scenario=document)


def test_the_estimate_that_is_perturbed_is_the_one_the_scenario_carries():
    origin = estimate_provenance(raw(BASELINE))
    assert origin["available"] is True
    assert origin["sulfur_mgkg"] == pytest.approx(8.0)
    assert origin["inventory_t"] is not None


def test_four_perturbations_are_declared_in_absolute_and_relative_terms():
    specs = perturbations(raw(BASELINE))
    assert [s["field"] for s in specs] == ["sulfur_mgkg", "sulfur_mgkg", "inventory", "inventory"]
    sulfur = [s["value"] for s in specs if s["field"] == "sulfur_mgkg"]
    assert sorted(sulfur) == pytest.approx([8.0 - SULFUR_ABSOLUTE_MGKG, 8.0 + SULFUR_ABSOLUTE_MGKG])
    stock = [s["value"] for s in specs if s["field"] == "inventory"]
    assert min(stock) == pytest.approx(specs[2]["estimate"] * (1 - INVENTORY_RELATIVE))


def test_a_perturbation_changes_only_the_main_tank_estimate():
    original = raw(BASELINE)
    before = copy.deepcopy(original)
    altered = apply(original, {"name": "x", "field": "sulfur_mgkg", "value": 9.0})
    assert original == before
    main = next(t for t in altered["tanks"] if t["tank_id"] == "main")
    assert main["properties"]["sulfur_mgkg"]["value"] == pytest.approx(9.0)
    assert main["inventory"] == next(t for t in before["tanks"] if t["tank_id"] == "main")["inventory"]
    assert [t for t in altered["tanks"] if t["tank_id"] != "main"] == \
           [t for t in before["tanks"] if t["tank_id"] != "main"]
    assert altered["crude"] == before["crude"]


def test_an_impossible_estimate_is_refused_not_silently_used():
    with pytest.raises(TankEstimateError):
        apply(raw(BASELINE), {"name": "x", "field": "sulfur_mgkg", "value": -1.0})
    with pytest.raises(TankEstimateError):
        apply(raw(BASELINE), {"name": "x", "field": "temperature", "value": 1.0})


def test_the_perturbed_estimate_reaches_the_calculation_despite_sulfur_from_chain():
    document = raw(BASELINE)
    main = next(t for t in document["tanks"] if t["tank_id"] == "main")
    assert main["sulfur_from_chain"] is True
    scenario = parse_scenario(apply(document, {"name": "x", "field": "sulfur_mgkg", "value": 20.0}))
    plain = parse_scenario(document)
    assert MakeDecision(plain).decide(budget=BUDGET)["status"] == "hold"
    assert MakeDecision(scenario).decide(budget=BUDGET)["status"] != "hold"


def test_a_stable_decision_is_reported_as_stable_with_every_perturbation_named():
    decision = decide(BASELINE)
    report = decision["tank_estimate"]
    assert report["available"] is True
    assert report["baseline_status"] == "hold" and report["baseline_plan"] == "hold"
    assert report["perturbations_evaluated"] == 4 and report["changed"] == 0
    assert report["sensitive"] is False
    assert [r["outcome"] for r in report["results"]] == ["same"] * 4
    assert "не меняется" in report["verdict"]


def test_a_sensitive_decision_names_the_perturbations_that_move_it():
    decision = decide(SOUR)
    report = decision["tank_estimate"]
    assert report["sensitive"] is True and report["changed"] == 2
    moved = [r for r in report["results"] if r["outcome"] == "changed"]
    assert {r["field"] for r in moved} == {"sulfur_mgkg"}
    for entry in moved:
        assert entry["plan_id"] != report["baseline_plan"]
        assert entry["immediate_action"] is not None


def test_the_operator_is_told_the_estimate_was_never_measured():
    decision = decide(SOUR)
    assert "не измеряли" in decision["reason"]
    item = next(i for i in risk_block(decision)["items"] if i["kind"] == "tank_estimate_sensitive")
    assert "уточнить прямой пробой" in item["text"]
    assert item["level"] == "medium"


def test_a_stable_decision_raises_no_risk_item():
    kinds = [i["kind"] for i in risk_block(decide(BASELINE))["items"]]
    assert "tank_estimate_sensitive" not in kinds


def test_the_check_reports_itself_unavailable_instead_of_guessing():
    check = TankEstimateCheck(load_scenario(BASELINE), raw(BASELINE))
    report = check.evaluate("hold", "hold", BUDGET)
    assert report["available"] is False and report["sensitive"] is False
    assert "не выполнена" in report["reason"]


def test_a_scenario_without_a_main_tank_is_reported_not_crashed():
    document = raw(BASELINE)
    document["tanks"] = [t for t in document["tanks"] if t["tank_id"] != "main"]
    check = TankEstimateCheck(load_scenario(BASELINE), document, scenario_parser=parse_scenario,
                              decision_factory=plain_decision)
    report = check.evaluate("hold", "hold", BUDGET)
    assert report["available"] is False and report["sensitive"] is False


def test_the_check_is_attached_to_every_decision_that_carries_a_robustness_check():
    decision = decide(BASELINE)
    assert decision["tank_estimate"] is not None
    entry = next(e for e in decision["trace"] if e["agent"] == "tank_estimate")
    assert entry["available"] is True and entry["evaluated"] == 4
    assert MakeDecision(load_scenario(BASELINE)).decide(budget=BUDGET)["tank_estimate"] is None


def test_the_limits_of_the_check_are_stated_next_to_its_verdict():
    limits = decide(BASELINE)["tank_estimate"]["limits"]
    assert any("прямыми пробами" in text for text in limits)
    assert any("не доверительный интервал" in text for text in limits)
