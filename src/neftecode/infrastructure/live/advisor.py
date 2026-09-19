from dataclasses import dataclass
from typing import Callable

import pandas as pd

from neftecode.domain.advisory.optimizer import DEFAULT_BUDGET
from neftecode.application.contracts import MEASURED_ORIGIN, LiveAdviceCommand
from neftecode.application.ports.robustness import RobustnessEvaluator
from neftecode.application.use_cases.get_live_advice import GetLiveAdvice

from .binding import bind_measurements, measurements_at
from .constants import (CASE_MAX_LAG_HOURS, DEFAULT_HORIZON_SHARE, DEFAULT_ONSET_HOURS, LiveError, MEASURED_TAGS,
                        RESPONSE_FILE, RESPONSE_SCHEMA_VERSION)
from .providers import (LocalForecastProvider, LocalForecastScenarioBinder, LocalScenarioProvider,
                        LocalSnapshotProvider)
from .response_model import (interval_coverage, linearize_response, load_response_model, response_lag,
                             validate_response_model)
from .state import bind_forecast, estimate_tank_sulfur, forecast_at, frozen_analyser_hold, state_at

__all__ = ["LiveAdviceAdapter", "LiveError", "MEASURED_ORIGIN", "MEASURED_TAGS", "RESPONSE_FILE",
           "RESPONSE_SCHEMA_VERSION", "CASE_MAX_LAG_HOURS", "DEFAULT_HORIZON_SHARE", "DEFAULT_ONSET_HOURS",
           "LocalForecastProvider", "LocalForecastScenarioBinder", "LocalScenarioProvider",
           "LocalSnapshotProvider", "bind_forecast", "bind_measurements", "estimate_tank_sulfur",
           "forecast_at", "frozen_analyser_hold", "interval_coverage", "linearize_response",
           "load_response_model", "measurements_at", "response_lag", "state_at", "validate_response_model"]


@dataclass
class LiveAdviceAdapter:

    signals: pd.DataFrame
    lab: pd.DataFrame
    online: pd.DataFrame
    bundle: dict
    raw_scenario: dict
    budget: int = DEFAULT_BUDGET
    robustness_evaluator: RobustnessEvaluator | None = None
    decision_factory: object | None = None
    robustness_factory: Callable | None = None
    response_model: dict | None = None
    coverage: dict | None = None

    def __post_init__(self):
        factory = self.robustness_factory
        if factory is None and self.robustness_evaluator is not None:
            factory = lambda scenario, raw: self.robustness_evaluator
        self._use_case = GetLiveAdvice(
            scenarios=LocalScenarioProvider(self.raw_scenario),
            snapshots=LocalSnapshotProvider(self.signals, self.lab, self.online, self.bundle),
            forecasts=LocalForecastProvider(self.signals, self.lab, self.online, self.bundle, self.coverage),
            binder=LocalForecastScenarioBinder(self.response_model),
            robustness_factory=factory,
            decision_factory=self.decision_factory,
        )

    def advise(self, at) -> dict:
        return self._use_case.execute(LiveAdviceCommand(
            at=at, scenario_id=self.raw_scenario.get("id", ""), budget=self.budget)).to_dict()
