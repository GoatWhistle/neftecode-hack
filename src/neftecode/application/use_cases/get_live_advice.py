"""The single live-advice orchestration use case."""
from dataclasses import dataclass
from typing import Callable, Mapping

from neftecode.application.contracts import LiveAdviceCommand, LiveAdviceResult, LiveForecast, LiveSnapshot
from neftecode.application.ports.live import (ForecastProvider, ForecastScenarioBinder,
                                               LiveSnapshotProvider, ScenarioProvider)
from neftecode.application.ports.robustness import RobustnessEvaluator
from neftecode.application.services.explain import explain
from neftecode.application.use_cases.make_decision import MakeDecision
from neftecode.domain.production.scenario import Scenario


RobustnessFactory = Callable[[Scenario, Mapping[str, object]], RobustnessEvaluator | None]


@dataclass
class GetLiveAdvice:
    """Coordinates scenario, snapshot, trust, forecast, binding and decision."""
    scenarios: ScenarioProvider
    snapshots: LiveSnapshotProvider
    forecasts: ForecastProvider
    binder: ForecastScenarioBinder
    robustness_factory: RobustnessFactory | None = None

    def execute(self, command: LiveAdviceCommand) -> LiveAdviceResult:
        if not isinstance(command, LiveAdviceCommand):
            raise TypeError("GetLiveAdvice.execute expects LiveAdviceCommand")
        if not isinstance(command.at, str) or not command.at.strip():
            raise ValueError("Нужно указать at")
        if not isinstance(command.scenario_id, str) or not command.scenario_id:
            raise ValueError("Нужно указать scenario_id")
        if not isinstance(command.budget, int) or isinstance(command.budget, bool) or command.budget <= 0:
            raise ValueError("budget должен быть положительным целым")
        scenario, raw = self.scenarios.get(command.scenario_id)
        snapshot = self.snapshots.snapshot(command.at)
        trust = dict(snapshot.trust)
        forecast = LiveForecast(None, None, None, None, False,
                                "Прогноз не вычислялся: источники не прошли проверку")
        if trust.get("usable") is True:
            forecast = self.forecasts.forecast(snapshot)
        if trust.get("usable") is not True:
            decision = self._decision(scenario, raw, snapshot, command.budget)
            return LiveAdviceResult(snapshot.at, command.scenario_id, snapshot.state, trust, forecast,
                                    decision, explain(decision, scenario),
                                    note="Источники не прошли проверку: решение принято без запуска моделей.")
        if not forecast.available:
            return LiveAdviceResult(snapshot.at, command.scenario_id, snapshot.state, trust, forecast,
                                    None, None, error=forecast.reason,
                                    note="Реальный прогноз недоступен; решение не выдаётся.")
        bound_scenario, bound_raw = self.binder.bind(raw, forecast)
        decision = self._decision(bound_scenario, bound_raw, snapshot, command.budget)
        return LiveAdviceResult(snapshot.at, command.scenario_id, snapshot.state, trust, forecast,
                                decision, explain(decision, bound_scenario),
                                bound_sulfur_mgkg=self._bound_sulfur(bound_scenario),
                                note=("Реальны: телеметрия, анализы, прогноз серы и проверка источников. "
                                      "Резервуары, цены, отклики и пределы T95/цетана заданы сценарием. "
                                      "Решение не разрешает выпуск товарного топлива."))

    def _decision(self, scenario, raw, snapshot: LiveSnapshot, budget: int):
        evaluator = self.robustness_factory(scenario, raw) if self.robustness_factory else None
        return MakeDecision(scenario, robustness_evaluator=evaluator).decide(
            state=dict(snapshot.state), trust_cfg=dict(snapshot.trust_cfg or {}), budget=budget, raw_scenario=dict(raw))

    @staticmethod
    def _bound_sulfur(scenario):
        try:
            return scenario.tank("main").property_value("sulfur_mgkg")
        except (KeyError, ValueError):
            return None
