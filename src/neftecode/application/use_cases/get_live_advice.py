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

#: Builds the decision use case: (scenario, robustness evaluator, live context) -> object with `decide(...)`.
DecisionFactory = Callable[[Scenario, RobustnessEvaluator | None, dict | None], object]


@dataclass
class GetLiveAdvice:
    """Coordinates scenario, snapshot, trust, forecast, binding and decision."""
    scenarios: ScenarioProvider
    snapshots: LiveSnapshotProvider
    forecasts: ForecastProvider
    binder: ForecastScenarioBinder
    robustness_factory: RobustnessFactory | None = None
    decision_factory: DecisionFactory | None = None

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
            decision = self._decision(scenario, raw, snapshot, command.budget, rejection, forecast)
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
        decision = self._decision(bound_scenario, bound_raw, snapshot, command.budget, forecast=forecast)
        warnings = list((bound_raw.get("measurement_binding") or {}).get("warnings") or ())
        return LiveAdviceResult(snapshot.at, command.scenario_id, snapshot.state, trust, forecast,
                                decision, explain(decision, bound_scenario), inventories=inventories,
                                bound_sulfur_mgkg=self._bound_sulfur(bound_scenario),
                                bound_inflow_sulfur_mgkg=self._bound_inflow(bound_scenario),
                                binding=binding_summary(bound_raw),
                                note=("".join(f"Внимание: {w} " for w in warnings) +
                                      "Реальны: телеметрия, анализы, прогноз серы притока, оценка серы резервуара "
                                      "по истории, проверка источников; уставки ГО и приток резервуара — измерения "
                                      "на момент решения, если они есть (см. binding). Запасы резервуаров, цены и "
                                      "пределы T95/цетана заданы сценарием. Решение не разрешает выпуск товарного топлива."))

    def _decision(self, scenario, raw, snapshot: LiveSnapshot, budget: int, rejection: DataRejection | None = None,
                  forecast: LiveForecast | None = None):
        evaluator = (self.robustness_factory(scenario, raw)
                     if self.robustness_factory and rejection is None else None)
        if self.decision_factory is None:
            maker = MakeDecision(scenario, robustness_evaluator=evaluator)
        else:
            context = {"at": snapshot.at, "forecast": forecast.to_dict() if forecast is not None else None}
            maker = self.decision_factory(scenario, evaluator, context)
        return maker.decide(
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


def binding_summary(raw: Mapping[str, object]) -> dict | None:
    """Сводка привязки по связанному сценарию: откуда уставки ГО, отклик, приток и окно резервуара."""
    stage = ((raw.get("stages") or {}).get("hydrotreating") or {})
    controls, model = stage.get("controls") or {}, stage.get("model") or {}
    main = next((t for t in raw.get("tanks") or [] if t.get("tank_id") == "main"), None)
    if main is None or not controls:
        return None

    def quantity(item):
        return None if not isinstance(item, dict) else {"value": item.get("value"), "source": item.get("source")}

    out = {
        "measurement_binding": raw.get("measurement_binding"),
        "controls": {name: {"current": quantity(spec.get("current")), "min": quantity(spec.get("min")),
                            "max": quantity(spec.get("max"))}
                     for name, spec in controls.items()},
        "response_model": {key: model.get(key) for key in
                           ("provenance", "beta_mgkg_per_c", "beta_ci", "weak_strong", "conversion_per_degree",
                            "reference_temp_c", "reference_space_velocity_m3h", "linearization_sulfur_mgkg")},
        "tank_inflow": quantity(main.get("inflow")),
        "tank_level_window_hours": (raw.get("policy") or {}).get("tank_level_window_hours"),
        "tank_sulfur_note": ((main.get("properties") or {}).get("sulfur_mgkg") or {}).get("note"),
        "inflow_sulfur_note": (main.get("inflow_sulfur_mgkg") or {}).get("note"),
    }
    return out
