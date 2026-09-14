from neftecode.application.contracts import (DecisionCommand, LiveAdviceCommand,
                                             PlanningCommand, ReplayCommand, LiveForecast, LiveSnapshot)
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


def test_live_use_case_orchestrates_typed_ports(monkeypatch):
    current = scenario()
    calls = []

    class Scenarios:
        def get(self, scenario_id):
            calls.append("scenario")
            return current, current.to_dict()

    class Snapshots:
        def snapshot(self, at):
            calls.append("snapshot")
            return LiveSnapshot(at, {}, {"usable": True, "fallback": False})

    class Forecasts:
        def forecast(self, snapshot):
            calls.append("forecast")
            return LiveForecast("test", 8.0, 7.0, 9.0, True, "")

    class Binder:
        def bind(self, raw, forecast):
            calls.append("bind")
            return current, raw

    class Decision:
        def __init__(self, *args, **kwargs):
            calls.append("decision")
        def decide(self, **kwargs):
            calls.append("decide")
            return {"status": "hold", "scenario_id": "baseline"}

    monkeypatch.setattr("neftecode.application.use_cases.get_live_advice.MakeDecision", Decision)
    monkeypatch.setattr("neftecode.application.use_cases.get_live_advice.explain", lambda *args: {"ok": True})
    result = GetLiveAdvice(Scenarios(), Snapshots(), Forecasts(), Binder()).execute(
        LiveAdviceCommand(at="2026-01-01T00:00:00", scenario_id="baseline"))
    assert calls == ["scenario", "snapshot", "forecast", "bind", "decision", "decide"]
    assert result.to_dict()["forecast"]["upper"] == 9.0


def test_explicit_data_rejection_stops_decision_before_search(monkeypatch):
    from neftecode.application.contracts import DataRejection

    use_case = MakeDecision(scenario())

    def forbidden(*args, **kwargs):
        raise AssertionError('Rejected data must not reach plan evaluation')

    monkeypatch.setattr(use_case.planner, 'evaluate', forbidden)
    result = use_case.execute(DecisionCommand(
        data_rejection=DataRejection('Snapshot rejected', ('fresh laboratory sample',))))
    assert result['status'] == 'refuse'
    assert result['selected_plan'] is None
    assert result['refusal'] == {'kind': 'data', 'missing': ['fresh laboratory sample']}
    assert result['trace'][0]['usable'] is False
