"""Regression net for the deterministic decision loop before the agent layer is added.

Every case the agent layer must never make less safe is pinned here: hold, recommendation,
refusal on data (both paths), refusal with no feasible plan, a failed final re-check, an
unknown limit and a fragile plan. The frozen hashes live in tests/test_architecture_baseline.py;
this file pins the meaning behind them so a change is explained, not only detected.
"""
import json
from dataclasses import replace
from pathlib import Path

import pytest

from neftecode.application.contracts import DataRejection, DecisionCommand
from neftecode.application.use_cases.make_decision import MakeDecision
from neftecode.domain.advisory.entities import CheckResult, GateResult
from neftecode.domain.shared.primitives import FAIL, HOLD, RECOMMEND_SCENARIO, REFUSE
from neftecode.evaluation.robustness import RobustnessCheck
from neftecode.infrastructure.config.scenario import parse_scenario

SCENARIOS = Path("config/scenarios")
BUDGET = 400

#: scenario -> (status, plan id, refusal kind, production, fragile, rounds, evaluated, trace agents, decision id)
EXPECTED = {
    "baseline": (HOLD, "hold", None, 300.0, False, 1, 200,
                 ["optimizer", "lookahead", "quality", "reliability", "robustness"], "eb7a8b51939efaaf"),
    "sour_crude": (RECOMMEND_SCENARIO, "c0025", None, 180.0, True, 1, 200,
                   ["optimizer", "lookahead", "quality", "reliability", "robustness"], "366e460dc398c321"),
    "ample_reserve": (RECOMMEND_SCENARIO, "c0029", None, 300.0, True, 1, 200,
                      ["optimizer", "lookahead", "quality", "reliability", "robustness"], "db5dc506cebc5d1b"),
    "no_feasible": (REFUSE, None, "no_feasible_plan", None, None, 2, 200, ["optimizer"], "1313333faf87fbcc"),
}


def raw(name: str) -> dict:
    return json.loads((SCENARIOS / f"{name}.json").read_text())


def decision_maker(document: dict) -> MakeDecision:
    scenario = parse_scenario(document)
    return MakeDecision(scenario, robustness_evaluator=RobustnessCheck(scenario, document,
                                                                       scenario_parser=parse_scenario))


def decide(name: str, **kwargs) -> dict:
    document = raw(name)
    return decision_maker(document).decide(budget=BUDGET, raw_scenario=document, **kwargs)


def healthy_state() -> dict:
    return {"decision_time": "2026-01-05T08:00:00",
            "lab_value": 8.0, "lab_age_hours": 5.0, "lab_usable": True,
            "pak_value": 8.4, "pak_age_minutes": 10.0, "pak_usable": True,
            "pak_frozen": False, "pak_conflict": False, "telemetry_missing_fraction": 0.0}


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_scenario_decision_meaning_is_pinned(name):
    status, plan_id, kind, production, fragile, rounds, evaluated, agents, decision_id = EXPECTED[name]
    decision = decide(name)
    optimizer = next(t for t in decision["trace"] if t["agent"] == "optimizer")
    assert decision["status"] == status
    assert (decision["selected_plan"] or {}).get("plan_id") == plan_id
    assert (decision["refusal"] or {}).get("kind") == kind
    assert decision["production_t"] == production
    assert (decision["robustness"] or {}).get("fragile") == fragile
    assert len(optimizer["rounds"]) == rounds
    assert optimizer["evaluated"] == evaluated
    assert [t["agent"] for t in decision["trace"]] == agents
    assert decision["decision_id"] == decision_id
    assert decision["commercial_release_allowed"] is False


@pytest.mark.parametrize("name", ["baseline", "sour_crude", "ample_reserve"])
def test_released_plans_pass_the_gate(name):
    decision = decide(name)
    assert decision["gate"]["feasible"] is True
    assert all(check["status"] == "pass" for check in decision["gate"]["checks"])


def test_repeated_decisions_are_identical():
    assert decide("sour_crude") == decide("sour_crude")


def test_healthy_state_keeps_the_hold():
    decision = decide("baseline", state=healthy_state())
    assert decision["status"] == HOLD
    assert decision["trace"][0] == {"agent": "data", "usable": True, "primary": decision["trace"][0]["primary"],
                                    "reasons": decision["trace"][0]["reasons"]}


def test_untrusted_state_refuses_on_data_before_search():
    state = dict(healthy_state(), lab_value=None, lab_usable=False, pak_frozen=True, pak_usable=False)
    decision = decide("baseline", state=state)
    assert decision["status"] == REFUSE
    assert decision["refusal"]["kind"] == "data"
    assert decision["refusal"]["missing"]
    assert [t["agent"] for t in decision["trace"]] == ["data"]


def test_explicit_data_rejection_refuses_without_evaluation(monkeypatch):
    maker = decision_maker(raw("sour_crude"))

    def forbidden(*args, **kwargs):
        raise AssertionError("rejected data must not reach plan evaluation")

    monkeypatch.setattr(maker.planner, "evaluate", forbidden)
    decision = maker.execute(DecisionCommand(data_rejection=DataRejection("snapshot rejected", ("lab",))))
    assert decision["status"] == REFUSE
    assert decision["refusal"] == {"kind": "data", "missing": ["lab"]}
    assert decision["selected_plan"] is None


def test_no_feasible_plan_refuses_with_examples():
    decision = decide("no_feasible")
    assert decision["status"] == REFUSE
    assert decision["refusal"]["examples"]
    assert decision["selected_plan"] is None and decision["gate"] is None


def _failing_gate(evaluation):
    failed = CheckResult("quality.sulfur_mgkg", FAIL, 12.0, 10.0, 0.0, reason="forced failure for the re-check test")
    return replace(evaluation, gate=GateResult(evaluation.gate.plan_id, (failed,)))


@pytest.mark.parametrize("name", ["baseline", "sour_crude"])
def test_a_failed_final_recheck_refuses(name, monkeypatch):
    document = raw(name)
    counting = decision_maker(document)
    original = counting.planner.evaluate
    calls = []

    def count(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(counting.planner, "evaluate", count)
    counting.decide(budget=BUDGET, raw_scenario=document)
    final_call = len(calls)

    failing = decision_maker(document)
    original_failing = failing.planner.evaluate
    seen = []

    def fail_last(*args, **kwargs):
        seen.append(1)
        evaluation = original_failing(*args, **kwargs)
        return _failing_gate(evaluation) if len(seen) == final_call else evaluation

    monkeypatch.setattr(failing.planner, "evaluate", fail_last)
    decision = failing.decide(budget=BUDGET, raw_scenario=document)
    assert decision["status"] == REFUSE
    assert decision["refusal"]["kind"] == "final_recheck_failed"
    assert decision["selected_plan"] is None
    assert decision["refusal"]["examples"] == ["forced failure for the re-check test"]


def test_an_unknown_limit_refuses():
    document = raw("baseline")
    document["product"]["t95_c"] = None
    decision = decision_maker(document).decide(budget=BUDGET, raw_scenario=document)
    assert decision["status"] == REFUSE
    assert decision["refusal"]["kind"] == "no_feasible_plan"


def test_a_fragile_plan_is_released_with_a_warning():
    decision = decide("sour_crude")
    assert decision["status"] == RECOMMEND_SCENARIO
    assert decision["robustness"]["fragile"] is True
    assert "надёжным не считается" in decision["reason"]


def test_the_legacy_review_vetoes_only_what_the_gate_already_rejects():
    """The deterministic quality/reliability roles are validators derived from gate checks."""
    maker = decision_maker(raw("baseline"))
    plans, _ = maker.planner.build_plans(BUDGET)
    for plan in plans[:60]:
        evaluation = maker.planner.evaluate(plan)
        review = {"quality": maker.quality.review(evaluation), "reliability": maker.reliability.review(evaluation)}
        if evaluation.feasible:
            assert review["quality"]["verdict"] == "pass"
            assert review["reliability"]["verdict"] == "pass"
