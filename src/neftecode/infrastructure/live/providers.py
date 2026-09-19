import copy

import pandas as pd

from neftecode.application.contracts import MEASURED_ORIGIN, LiveForecast, LiveSnapshot
from neftecode.application.ports.live import ForecastBindingError
from neftecode.application.services.trust import DataTrustAgent
from neftecode.infrastructure.config.scenario import parse_scenario
from neftecode.infrastructure.live.origin import validate_origin

from .binding import bind_measurements, _main_density
from .constants import LiveError
from .state import bind_forecast, forecast_at, state_at


class LocalScenarioProvider:
    def __init__(self, raw_scenario: dict):
        self.raw_scenario = raw_scenario

    def get(self, scenario_id):
        scenario = parse_scenario(self.raw_scenario)
        if scenario.scenario_id != scenario_id:
            raise LiveError(f"Сценарий «{scenario_id}» не совпадает с загруженным")
        return scenario, copy.deepcopy(self.raw_scenario)


class LocalSnapshotProvider:
    def __init__(self, signals, lab, online, bundle):
        self.signals, self.lab, self.online, self.bundle = signals, lab, online, bundle

    def snapshot(self, at):
        when = validate_origin(at, self.bundle)
        state = state_at(self.signals, self.lab, self.online, self.bundle, when)
        trust = DataTrustAgent(self.bundle["config"]).assess(state)
        return LiveSnapshot(when.isoformat(), state, trust.to_dict(), trust_cfg=self.bundle["config"],
                            trust_origin="derived:model.pkl")


class LocalForecastProvider:
    def __init__(self, signals, lab, online, bundle, coverage: dict | None = None):
        self.signals, self.lab, self.online, self.bundle = signals, lab, online, bundle
        self.coverage = coverage or {}

    def forecast(self, snapshot):
        raw = forecast_at(self.signals, self.lab, self.online, self.bundle,
                          pd.Timestamp(snapshot.at), fallback=snapshot.trust.get("fallback", False))
        coverage = self.coverage
        if coverage and "coverage_target" not in coverage:
            coverage = coverage.get(raw.get("model"), {})
        return LiveForecast.from_dict({**raw, **(coverage or {})})


class LocalForecastScenarioBinder:

    def __init__(self, response: dict | None = None):
        self.response = response

    def bind(self, raw_scenario, forecast, snapshot=None):
        try:
            state = dict(snapshot.state) if snapshot is not None else None
            raw = dict(raw_scenario)
            if state is not None and state.get("origin") == MEASURED_ORIGIN:
                raw = bind_measurements(raw, state.get("measurements") or {},
                                        {"density_kgm3": _main_density(raw)}, self.response, forecast.to_dict(),
                                        at=snapshot.at)
            raw = bind_forecast(raw, forecast.to_dict(), state=state)
            return parse_scenario(raw), raw
        except (ValueError, KeyError, TypeError) as exc:
            raise ForecastBindingError(str(exc)) from exc
