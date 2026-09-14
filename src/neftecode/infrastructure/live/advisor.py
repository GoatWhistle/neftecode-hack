"""Joining the real measurements to the scenario advisor at one moment in time.

The two halves of the system meet here and nowhere else:

* the **real** half — telemetry, laboratory and analyser readings at a past moment, the trained
  forecast of hydrotreated sulfur, and the data-trust verdict built from them;
* the **scenario** half — tanks, prices, product limits, response models and the agent loop.

The join is one number and one state: the forecast of hydrotreated sulfur becomes the sulfur of
the main blending component, and the trust verdict becomes the state the data agent sees. Every
other blending quantity stays declared by the scenario, which is why the result keeps saying so.

The forecast's upper bound is used, not its point value. A point estimate that happens to sit
below the limit is not evidence that the limit holds, and the earlier prototype's own report
said as much.
"""
from dataclasses import dataclass
import copy

import numpy as np
import pandas as pd

from neftecode.infrastructure.data.data import build_features, recent_quality_history
from neftecode.application.ports.live import ForecastBindingError
from neftecode.application.ports.robustness import RobustnessEvaluator
from neftecode.application.contracts import LiveForecast, LiveSnapshot, LiveAdviceCommand
from neftecode.application.use_cases.get_live_advice import GetLiveAdvice
from neftecode.infrastructure.ml.forecast import interval, predict_candidate
from neftecode.infrastructure.live.origin import validate_origin
from neftecode.infrastructure.config.scenario import parse_scenario
from neftecode.application.services.trust import DataTrustAgent


class LiveError(ValueError):
    """Raised when the real measurements cannot be joined to a scenario."""


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
        return LiveSnapshot(when.isoformat(), state, trust.to_dict(), trust_cfg=self.bundle["config"])


class LocalForecastProvider:
    def __init__(self, signals, lab, online, bundle):
        self.signals, self.lab, self.online, self.bundle = signals, lab, online, bundle

    def forecast(self, snapshot):
        raw = forecast_at(self.signals, self.lab, self.online, self.bundle,
                          pd.Timestamp(snapshot.at), fallback=snapshot.trust.get("fallback", False))
        return LiveForecast.from_dict(raw)


class LocalForecastScenarioBinder:
    def bind(self, raw_scenario, forecast, snapshot=None):
        try:
            state = dict(snapshot.state) if snapshot is not None else None
            raw = bind_forecast(dict(raw_scenario), forecast.to_dict(), state=state)
            return parse_scenario(raw), raw
        except (ValueError, KeyError, TypeError) as exc:
            raise ForecastBindingError(str(exc)) from exc


def state_at(signals, lab, online, bundle, when) -> dict:
    """The data-trust state built from what was actually available at `when`."""
    _, metadata = build_features(signals, lab, online, [when], bundle["config"])
    state = {}
    for key, value in metadata.iloc[0].items():
        if pd.isna(value):
            state[key] = None
        elif isinstance(value, pd.Timestamp):
            state[key] = value.isoformat()
        elif isinstance(value, np.generic):
            state[key] = value.item()
        else:
            state[key] = value
    state["origin"] = "real_measurements_at_decision_time"
    state.update(recent_quality_history(lab, online, when, bundle["config"]))
    return state


def forecast_at(signals, lab, online, bundle, when, fallback: bool = False) -> dict:
    """Forecast of hydrotreated sulfur, with the interval the calibration produced."""
    x, _ = build_features(signals, lab, online, [when], bundle["config"])
    name = bundle["fallback"] if fallback else bundle["selected"]
    value = float(predict_candidate(bundle, name, x)[0])
    if not np.isfinite(value):
        return {"model": name, "value": None, "lower": None, "upper": None, "available": False,
                "reason": "Выбранный прогноз недоступен на этот момент"}
    low, high = interval(value, bundle["radii"][name])
    return {"model": name, "value": value, "lower": float(low), "upper": float(high),
            "available": True,
            "reason": "Прогноз лабораторной серы после гидроочистки на горизонт эксперимента"}


def _policy_number(raw: dict, key: str, low: float, high: float) -> float:
    value = (raw.get("policy") or {}).get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not np.isfinite(value) \
            or not low <= value <= high:
        raise LiveError(f"policy.{key}: нужно число в пределах [{low:g}, {high:g}], получено {value!r}")
    return float(value)


def estimate_tank_sulfur(raw: dict, state: dict) -> dict:
    """Sulfur of what is already stored in the main tank, from what flowed in before the decision.

    The tank is treated as well mixed over its refresh window (inventory over inflow): the mean of
    trusted analyser readings in that window. Readings inside a flat run of at least an hour are not
    trusted. With too few trusted readings the laboratory mean in the window is used (at least two
    results); otherwise the level is unknown and no advice may be produced.
    """
    window = _policy_number(raw, "tank_level_window_hours", 1.0, 72.0)
    coverage_min = _policy_number(raw, "tank_level_min_coverage", 0.0, 1.0)
    when = pd.Timestamp(state.get("decision_time"))
    if pd.isna(when):
        raise LiveError("Состояние не содержит времени решения: уровень резервуара не оценивается")
    if window > float(state.get("quality_history_hours") or 0):
        raise LiveError("История показаний короче окна резервуара: уровень не оценивается")
    start = when - pd.Timedelta(value=window, unit="h")
    hours = [(pd.Timestamp(t), m, n) for t, m, n in state.get("pak_trusted_hourly") or []]
    inside = [(m, n) for t, m, n in hours if t >= start.floor("h") and t <= when]
    count = sum(n for _, n in inside)
    per_hour = state.get("pak_expected_per_hour")
    coverage = count / (window * per_hour) if per_hour else 0.0
    if count and coverage >= coverage_min:
        value = sum(m * n for m, n in inside) / count
        return {"value": value, "source": "pak", "coverage": min(1.0, coverage), "n": count, "window_hours": window}
    lab = [v for t, v in state.get("lab_recent") or [] if start < pd.Timestamp(t) <= when]
    if len(lab) >= 2:
        return {"value": float(np.mean(lab)), "source": "lims", "coverage": coverage, "n": len(lab),
                "window_hours": window}
    raise LiveError(f"Уровень серы в резервуаре не оценивается: за {window:g} ч доверенных показаний ПАК "
                    f"{coverage:.0%} при требуемых {coverage_min:.0%} и проб ЛИМС {len(lab)}")


def bind_forecast(raw: dict, forecast: dict, tank_id: str = "main", state: dict | None = None) -> dict:
    """Bind a hydrotreated-sulfur forecast to the main tank, on a copy.

    The forecast describes the stream leaving hydrotreating, not the stored product, so its UPPER
    bound becomes the sulfur of the tank's inflow: the blend is judged against what the incoming
    stream could be, and the stored mass dilutes it as it does in the plant. With a measurement
    state the stored sulfur is estimated from history; without one (synthetic scenes) the scenario's
    declared stored sulfur is kept.
    """
    if not forecast.get("available"):
        raise LiveError(forecast.get("reason", "Прогноз недоступен"))
    values = tuple(forecast.get(key) for key in ("lower", "value", "upper"))
    if (not all(isinstance(value, (int, float)) and not isinstance(value, bool)
                and np.isfinite(value) for value in values)
            or not values[0] <= values[1] <= values[2]):
        raise LiveError("Прогноз содержит некорректное значение или доверительный интервал")
    if not isinstance(forecast.get("model"), str) or not forecast["model"].strip():
        raise LiveError("Прогноз не содержит версию модели")
    out = copy.deepcopy(raw)
    for tank in out["tanks"]:
        if tank["tank_id"] == tank_id:
            # A measurement-derived value outranks the chain model.
            tank["sulfur_from_chain"] = False
            inflow = float(forecast["upper"])
            tank["inflow_sulfur_mgkg"] = {
                "value": round(inflow, 4), "unit": "мг/кг", "source": "derived",
                "note": (f"Сера притока с гидроочистки: верхняя граница прогноза модели {forecast['model']} "
                         f"на момент решения; точечная оценка {forecast['value']:.3f} мг/кг.")}
            if state is not None and state.get("origin") == "real_measurements_at_decision_time":
                level = estimate_tank_sulfur(out, state)
                tank["properties"]["sulfur_mgkg"] = {
                    "value": round(level["value"], 4), "unit": "мг/кг", "source": "derived",
                    "note": (f"Сера содержимого резервуара: среднее {level['n']} доверенных показаний "
                             f"{'ПАК' if level['source'] == 'pak' else 'ЛИМС'} за {level['window_hours']:g} ч "
                             f"окна обновления; допущение полного перемешивания.")}
            return out
    raise LiveError(f"Резервуар {tank_id} не описан в сценарии")


@dataclass
class LiveAdviceAdapter:
    """One decision at one real moment, through the full agent loop."""

    signals: pd.DataFrame
    lab: pd.DataFrame
    online: pd.DataFrame
    bundle: dict
    raw_scenario: dict
    budget: int = 400
    robustness_evaluator: RobustnessEvaluator | None = None

    def __post_init__(self):
        self._use_case = GetLiveAdvice(
            scenarios=LocalScenarioProvider(self.raw_scenario),
            snapshots=LocalSnapshotProvider(self.signals, self.lab, self.online, self.bundle),
            forecasts=LocalForecastProvider(self.signals, self.lab, self.online, self.bundle),
            binder=LocalForecastScenarioBinder(),
            robustness_factory=(lambda scenario, raw: self.robustness_evaluator),
        )

    def advise(self, at) -> dict:
        return self._use_case.execute(LiveAdviceCommand(
            at=at, scenario_id=self.raw_scenario.get("id", ""), budget=self.budget)).to_dict()
