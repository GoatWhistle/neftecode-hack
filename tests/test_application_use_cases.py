from neftecode.application.ports import LiveAdviceGateway
from neftecode.application.contracts import (DecisionCommand, LiveAdviceCommand,
                                             PlanningCommand, ReplayCommand)
from neftecode.application.use_cases.get_live_advice import GetLiveAdvice
from neftecode.application.use_cases.make_decision import MakeDecision
from neftecode.application.use_cases.plan_operation import PlanOperation
from neftecode.application.use_cases.replay_decisions import ReplayDecisions
from neftecode.infrastructure.config.scenario import load_scenario


def scenario():
    return load_scenario("config/scenarios/baseline.json")


def test_use_cases_expose_execute_entry_points():
    current = scenario()
    assert isinstance(PlanOperation(current).execute(PlanningCommand(budget=1)), dict)
    assert isinstance(MakeDecision(current).execute(DecisionCommand(budget=1)), dict)
    replay = ReplayDecisions(current, budget=1).execute(ReplayCommand(moments=[], mode="simulated"))
    assert replay["records"] == []


def test_live_advice_delegates_through_port():
    class Gateway:
        def advise(self, at):
            return {"at": at, "source": "gateway"}

    assert isinstance(Gateway(), LiveAdviceGateway)
    assert GetLiveAdvice(Gateway()).execute(LiveAdviceCommand(at="2026-01-01T00:00:00"))["source"] == "gateway"
