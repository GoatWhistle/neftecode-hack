"""The single live-advice orchestration use case."""
from dataclasses import dataclass
from typing import Callable, Mapping

from neftecode.application.contracts import DataRejection, LiveAdviceCommand, LiveAdviceResult, LiveForecast, LiveSnapshot
from neftecode.application.ports.live import (ForecastBindingError, ForecastProvider, ForecastScenarioBinder,
                                               LiveSnapshotProvider, ScenarioProvider)
from neftecode.application.ports.robustness import RobustnessEvaluator
from neftecode.application.services.explain import explain
from neftecode.application.use_cases.make_decision import MakeDecision
from neftecode.domain.production.scenario import Scenario
from neftecode.domain.production.inventory import initial_state


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
        inventories = {key: tank.inventory_t for key, tank in initial_state(scenario).items()}
        forecast = LiveForecast(None, None, None, None, False,
                                "Прогноз не вычислялся: источники не прошли проверку")
        if trust.get("usable") is True:
            forecast = self.forecasts.forecast(snapshot)
        if trust.get("usable") is not True:
            rejection = DataRejection(
                trust.get("refusal_reason") or "Источники snapshot не прошли проверку доверия",
                tuple(trust.get("missing_requirements") or ()),
            )
            decision = self._decision(scenario, raw, snapshot, command.budget, rejection)
            return LiveAdviceResult(snapshot.at, command.scenario_id, snapshot.state, trust, forecast,
                                    decision, explain(decision, scenario),
                                    note="Источники не прошли проверку: решение принято без запуска моделей.",
                                    inventories=inventories)
        if not forecast.available:
            return LiveAdviceResult(snapshot.at, command.scenario_id, snapshot.state, trust, forecast,
                                    None, None, error=forecast.reason,
                                    note="Реальный прогноз недоступен; решение не выдаётся.", inventories=inventories)
        try:
            bound_scenario, bound_raw = self.binder.bind(raw, forecast, snapshot)
        except ForecastBindingError as exc:
            return LiveAdviceResult(
                snapshot.at, command.scenario_id, snapshot.state, trust, forecast, None, None,
                error=str(exc), error_kind="forecast_binding_failed", inventories=inventories,
                note="Реальный прогноз не удалось связать со сценарием; решение не выдаётся.",
            )
        decision = self._decision(bound_scenario, bound_raw, snapshot, command.budget)
        return LiveAdviceResult(snapshot.at, command.scenario_id, snapshot.state, trust, forecast,
                                decision, explain(decision, bound_scenario), inventories=inventories,
                                bound_sulfur_mgkg=self._bound_sulfur(bound_scenario),
                                bound_inflow_sulfur_mgkg=self._bound_inflow(bound_scenario),
                                note=("Реальны: телеметрия, анализы, прогноз серы притока, оценка серы резервуара "
                                      "по истории и проверка источников. "
                                      "Резервуары, цены, отклики и пределы T95/цетана заданы сценарием. "
                                      "Решение не разрешает выпуск товарного топлива."))

    def _decision(self, scenario, raw, snapshot: LiveSnapshot, budget: int, rejection: DataRejection | None = None):
        evaluator = (self.robustness_factory(scenario, raw)
                     if self.robustness_factory and rejection is None else None)
        return MakeDecision(scenario, robustness_evaluator=evaluator).decide(
            state=dict(snapshot.state), trust_cfg=dict(snapshot.trust_cfg or {}), budget=budget, raw_scenario=dict(raw), data_rejection=rejection)

    @staticmethod
    def _bound_inflow(scenario):
        try:
            inflow = scenario.tank("main").inflow_sulfur
        except KeyError:
            return None
        return None if inflow is None else inflow.value

    @staticmethod
    def _bound_sulfur(scenario):
        try:
            return scenario.tank("main").property_value("sulfur_mgkg")
        except (KeyError, ValueError):
            return None
