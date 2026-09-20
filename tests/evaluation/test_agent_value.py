import json
from pathlib import Path

import pytest

from neftecode.application.use_cases.make_decision import MakeDecision
from neftecode.evaluation.agent_value import run_agent_value_study
from neftecode.infrastructure.config.scenario import parse_scenario


def raw(name="baseline"):
    return json.loads(Path(f"config/scenarios/{name}.json").read_text(encoding="utf-8"))


def core_runner(scenario, document, budget):
    return MakeDecision(scenario).decide(budget=budget)


def test_same_input_study_records_rules_core_agent_latency_and_stability():
    ticks = iter(range(100))
    report = run_agent_value_study(
        [("normal", raw())], budget=100, scenario_parser=parse_scenario,
        agentic_runner=core_runner, repeats=2, clock=lambda: next(ticks),
    )
    case = report["cases"][0]
    assert case["core"]["identity"] == case["agentic"]["identity"]
    assert case["threshold"]["feasible"] is True
    assert case["agentic"]["latency_seconds"] == [1, 1]
    assert case["agentic"]["stable"] is True
    assert case["needless_refusal"] is False


def test_needless_agent_refusal_is_counted_explicitly():
    def refusing(scenario, document, budget):
        decision = MakeDecision(scenario).decide(budget=budget)
        return {**decision, "status": "refuse", "selected_plan": None,
                "refusal": {"kind": "agent_rejected"}}

    report = run_agent_value_study(
        [("normal", raw())], budget=100, scenario_parser=parse_scenario,
        agentic_runner=refusing, repeats=2,
    )
    assert report["cases"][0]["needless_refusal"] is True


def test_stability_requires_repeated_runs():
    with pytest.raises(ValueError, match="минимум два"):
        run_agent_value_study([], budget=10, scenario_parser=parse_scenario,
                              agentic_runner=core_runner, repeats=1)
