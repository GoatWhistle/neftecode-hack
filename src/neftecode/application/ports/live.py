from typing import Mapping, Protocol

from neftecode.application.contracts import LiveForecast, LiveSnapshot
from neftecode.domain.production.scenario import Scenario


class ForecastBindingError(ValueError):
    pass


class ScenarioProvider(Protocol):
    def get(self, scenario_id: str) -> tuple[Scenario, Mapping[str, object]]: ...


class LiveSnapshotProvider(Protocol):
    def snapshot(self, at: str) -> LiveSnapshot: ...


class ForecastProvider(Protocol):
    def forecast(self, snapshot: LiveSnapshot) -> LiveForecast: ...


class ForecastScenarioBinder(Protocol):
    def bind(self, raw_scenario: Mapping[str, object], forecast: LiveForecast,
             snapshot: LiveSnapshot | None = None) -> tuple[Scenario, Mapping[str, object]]: ...
