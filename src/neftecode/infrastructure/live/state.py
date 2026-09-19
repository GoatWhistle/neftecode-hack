import copy
import math

import numpy as np
import pandas as pd

from neftecode.application.contracts import MEASURED_ORIGIN
from neftecode.infrastructure.data.data import build_features, recent_quality_history
from neftecode.infrastructure.ml.forecast import interval, predict_candidate

from .binding import measurements_at
from .constants import LiveError, _finite_number
from .response_model import linearize_response


def state_at(signals, lab, online, bundle, when) -> dict:
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
    state["origin"] = MEASURED_ORIGIN
    state.update(recent_quality_history(lab, online, when, bundle["config"]))
    state["measurements"] = measurements_at(signals, when, bundle["config"])
    return state


def forecast_at(signals, lab, online, bundle, when, fallback: bool = False) -> dict:
    x, _ = build_features(signals, lab, online, [when], bundle["config"])
    name = bundle["fallback"] if fallback else bundle["selected"]
    value = float(predict_candidate(bundle, name, x)[0])
    if not np.isfinite(value):
        return {"model": name, "value": None, "lower": None, "upper": None, "available": False,
                "reason": "Выбранный прогноз недоступен на этот момент"}
    low, high = interval(value, bundle["radii"][name])
    reason = "Прогноз лабораторной серы после гидроочистки на горизонт эксперимента"
    if name == "last_pak_bc":
        reason += "; ПАК скорректирован причинной медианой 20 последних доступных пар ЛИМС−ПАК"
    return {"model": name, "value": value, "lower": float(low), "upper": float(high),
            "available": True, "reason": reason}


def _policy_number(raw: dict, key: str, low: float, high: float) -> float:
    value = (raw.get("policy") or {}).get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not np.isfinite(value) \
            or not low <= value <= high:
        raise LiveError(f"policy.{key}: нужно число в пределах [{low:g}, {high:g}], получено {value!r}")
    return float(value)


def estimate_tank_sulfur(raw: dict, state: dict) -> dict:
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


def frozen_analyser_hold(raw: dict, state: dict) -> dict | None:
    if not state.get("pak_frozen"):
        return None
    value, at = state.get("pak_last_trusted_value"), state.get("pak_last_trusted_time")
    when = pd.Timestamp(state.get("decision_time"))
    if value is None or at is None or pd.isna(when):
        return None
    max_age = _policy_number(raw, "frozen_hold_max_age_hours", 0.0, 72.0)
    age = (when - pd.Timestamp(at)).total_seconds() / 3600
    if age > max_age:
        return None
    later_lab = [(pd.Timestamp(t), v) for t, v in state.get("lab_recent") or [] if pd.Timestamp(t) > pd.Timestamp(at)]
    if later_lab:
        sampled, lab_value = max(later_lab)
        return {"value": float(lab_value), "source": "lims", "at": sampled.isoformat()}
    return {"value": float(value), "source": "pak", "at": pd.Timestamp(at).isoformat()}


def bind_forecast(raw: dict, forecast: dict, tank_id: str = "main", state: dict | None = None) -> dict:
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
            tank["sulfur_from_chain"] = False
            inflow = float(forecast["upper"])
            note = (f"Сера притока с гидроочистки: верхняя граница прогноза модели {forecast['model']} "
                    f"на момент решения; точечная оценка {forecast['value']:.3f} мг/кг.")
            target, actual = forecast.get("coverage_target"), forecast.get("coverage_test")
            if _finite_number(target) and _finite_number(actual):
                note += (f" Интервал откалиброван на покрытие {target:.0%}; фактическое покрытие на тесте 2026 — "
                         f"{actual:.1%}: верхняя граница не гарантирует предел при смене режима.")
            measured = state is not None and state.get("origin") == "real_measurements_at_decision_time"
            hold = frozen_analyser_hold(out, state) if measured else None
            if hold is not None and hold["value"] > inflow:
                inflow = hold["value"]
                note += (f" Анализатор завис: приток не ниже последнего доверенного значения "
                         f"{hold['value']:.3f} мг/кг ({'ЛИМС' if hold['source'] == 'lims' else 'ПАК'}, {hold['at']}).")
            model = ((out.get("stages") or {}).get("hydrotreating") or {}).get("model") or {}
            if model.get("provenance") == "derived" and _finite_number(model.get("beta_mgkg_per_c")) \
                    and model.get("linearization_sulfur_mgkg") != inflow:
                linearize_response(model, inflow, "сера притока после удержания зависшего ПАК")
            if measured:
                level = estimate_tank_sulfur(out, state)
                tank["properties"]["sulfur_mgkg"] = {
                    "value": round(level["value"], 4), "unit": "мг/кг", "source": "derived",
                    "note": (f"Сера содержимого резервуара: среднее {level['n']} доверенных показаний "
                             f"{'ПАК' if level['source'] == 'pak' else 'ЛИМС'} за {level['window_hours']:g} ч "
                             f"окна обновления; допущение полного перемешивания.")}
                q, mass = float(tank["inflow"]["value"]), float(tank["inventory"]["value"])
                if q > 0 and mass > 0:
                    shift = (inflow - level["value"]) * (1 - math.exp(-q * 3.0 / mass))
                    note += (f" Вклад прогноза за 3 ч: {shift:+.3f} мг/кг к сере резервуара "
                             f"(приток {q:g} т/ч, запас {mass:g} т).")
            tank["inflow_sulfur_mgkg"] = {"value": round(inflow, 4), "unit": "мг/кг", "source": "derived",
                                          "note": note}
            return out
    raise LiveError(f"Резервуар {tank_id} не описан в сценарии")
