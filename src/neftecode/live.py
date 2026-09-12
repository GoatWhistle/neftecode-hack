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
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .data import build_features
from .explain import explain
from .forecast import interval, predict_candidate
from .inventory import initial_state
from .orchestrator import Orchestrator
from .runtime import validate_origin
from .scenario import ScenarioError, parse_scenario
from .trust import DataTrustAgent
from .ui import Screen


class LiveError(ValueError):
    """Raised when the real measurements cannot be joined to a scenario."""


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


def bind_forecast(raw: dict, forecast: dict, tank_id: str = "main") -> dict:
    """Put the forecast's UPPER bound into the main component's sulfur, on a copy.

    Using the upper bound is the conservative reading: the blend is judged against what the
    sulfur could be, not against the middle of the interval.
    """
    if not forecast.get("available"):
        raise LiveError(forecast.get("reason", "Прогноз недоступен"))
    out = copy.deepcopy(raw)
    for tank in out["tanks"]:
        if tank["tank_id"] == tank_id:
            # A measurement-derived value outranks the chain model for the CURRENT level.
            tank["sulfur_from_chain"] = False
            tank["properties"]["sulfur_mgkg"] = {
                "value": round(forecast["upper"], 4), "unit": "мг/кг", "source": "derived",
                "note": (f"Верхняя граница прогноза модели {forecast['model']} на момент решения. "
                         f"Точечная оценка {forecast['value']:.3f} мг/кг сама по себе допуском "
                         f"не является.")}
            return out
    raise LiveError(f"Резервуар {tank_id} не описан в сценарии")


@dataclass
class LiveAdvisor:
    """One decision at one real moment, through the full agent loop."""

    signals: pd.DataFrame
    lab: pd.DataFrame
    online: pd.DataFrame
    bundle: dict
    raw_scenario: dict
    budget: int = 400

    def advise(self, at) -> dict:
        when = validate_origin(at, self.bundle)
        state = state_at(self.signals, self.lab, self.online, self.bundle, when)
        trust = DataTrustAgent(self.bundle["config"]).assess(state)

        forecast = {"model": None, "value": None, "lower": None, "upper": None,
                    "available": False, "reason": "Прогноз не вычислялся: источники не прошли проверку"}
        result = {"at": when.isoformat(), "state": state, "forecast": forecast,
                  "trust": trust.to_dict(), "scenario_id": self.raw_scenario.get("id")}

        if not trust.usable:
            scenario = parse_scenario(self.raw_scenario)
            decision = Orchestrator(scenario).decide(state=state, budget=self.budget,
                                                     trust_cfg=self.bundle["config"],
                                                     raw_scenario=self.raw_scenario)
            return {**result, "decision": decision,
                    "explanation": explain(decision, scenario),
                    "note": "Источники не прошли проверку: решение принято без запуска моделей."}
        # Only an admissible state may reach a prediction model. A rejected analyser also
        # excludes models using its features, even if the laboratory remains usable.
        forecast = forecast_at(self.signals, self.lab, self.online, self.bundle, when,
                               fallback=trust.fallback_mode)
        result["forecast"] = forecast
        try:
            raw = bind_forecast(self.raw_scenario, forecast)
            scenario = parse_scenario(raw)
        except (LiveError, ScenarioError) as exc:
            return {**result, "decision": None, "explanation": None,
                    "error": str(exc),
                    "note": "Реальный прогноз не удалось связать со сценарием; решение не выдаётся."}

        decision = Orchestrator(scenario).decide(state=state, budget=self.budget,
                                                 trust_cfg=self.bundle["config"],
                                                 raw_scenario=raw)
        return {
            **result,
            "decision": decision,
            "explanation": explain(decision, scenario),
            "bound_sulfur_mgkg": scenario.tank("main").property_value("sulfur_mgkg"),
            "note": ("Реальны: телеметрия, анализы, прогноз серы и проверка источников. "
                     "Резервуары, цены, отклики и пределы T95/цетана заданы сценарием. "
                     "Решение не разрешает выпуск товарного топлива."),
        }

    def screen(self, result: dict) -> dict:
        """Payload for the operator screen, carrying the real source verdicts."""
        if result.get("decision") is None:
            from .ui import error_payload
            return error_payload(result.get("error", "Решение не получено"))
        scenario = parse_scenario(
            bind_forecast(self.raw_scenario, result["forecast"])
            if result["forecast"].get("available") and result["trust"]["usable"]
            else self.raw_scenario)
        sources = [v for v in result["trust"]["sources"].values()]
        return Screen(result["decision"], result["explanation"],
                      inventories={k: v.inventory_t for k, v in initial_state(scenario).items()},
                      sources=sources).payload()
