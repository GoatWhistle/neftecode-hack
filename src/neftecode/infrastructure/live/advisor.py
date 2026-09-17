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
from pathlib import Path
from typing import Callable
import copy
import json
import math

import numpy as np
import pandas as pd

from neftecode.infrastructure.data.data import build_features, frozen_rule, recent_quality_history
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
        return LiveSnapshot(when.isoformat(), state, trust.to_dict(), trust_cfg=self.bundle["config"],
                            trust_origin="derived:model.pkl")


class LocalForecastProvider:
    def __init__(self, signals, lab, online, bundle, coverage: dict | None = None):
        self.signals, self.lab, self.online, self.bundle = signals, lab, online, bundle
        #: {"coverage_target": …, "coverage_test": …} из metrics.json — честность интервала в каждом решении.
        self.coverage = coverage or {}

    def forecast(self, snapshot):
        raw = forecast_at(self.signals, self.lab, self.online, self.bundle,
                          pd.Timestamp(snapshot.at), fallback=snapshot.trust.get("fallback", False))
        return LiveForecast.from_dict({**raw, **self.coverage})


class LocalForecastScenarioBinder:
    """Связывает прогноз и, для реального состояния, измерения тегов со сценарием.

    Порядок фиксирован: сначала `bind_measurements` (уставки, модель отклика, приток и окно
    резервуара), потом `bind_forecast` — оценка серы резервуара читает уже пересчитанное окно.
    `response` — содержимое C2 (`load_response_model`) или None, если отклик по данным не загружен.
    """

    def __init__(self, response: dict | None = None):
        self.response = response

    def bind(self, raw_scenario, forecast, snapshot=None):
        try:
            state = dict(snapshot.state) if snapshot is not None else None
            raw = dict(raw_scenario)
            if state is not None and state.get("origin") == MEASURED_ORIGIN:
                raw = bind_measurements(raw, state.get("measurements") or {},
                                        {"density_kgm3": _main_density(raw)}, self.response, forecast.to_dict())
            raw = bind_forecast(raw, forecast.to_dict(), state=state)
            return parse_scenario(raw), raw
        except (ValueError, KeyError, TypeError) as exc:
            raise ForecastBindingError(str(exc)) from exc


MEASURED_ORIGIN = "real_measurements_at_decision_time"
#: Теги, чьи значения на момент решения попадают в сценарий: температура входа Р-202, массовый
#: расход сырья и расход гидроочищенного ДТ в цех №8 (справочник 24-2000 от 16.09).
MEASURED_TAGS = ("ht.T6", "ht.F9", "ht.F26")
RESPONSE_SCHEMA_VERSION = "v1"
RESPONSE_FILE = "config/response_model.json"
#: Задержка отклика ГО по исследованию: β — средний накопленный отклик через 3–8 ч, раньше 3 ч эффект не засчитывается;
#: доля β, засчитываемая в пределах горизонта кейса, объявляется в C2 (`horizon_response_share`), без поля — вся.
DEFAULT_ONSET_HOURS = 3.0
DEFAULT_HORIZON_SHARE = 1.0
CASE_MAX_LAG_HOURS = 3.0


def measurements_at(signals: pd.DataFrame, when, cfg: dict) -> dict:
    """Последнее не-NaN значение каждого тега не старше pak_age_periods × период опроса; иначе None."""
    when = pd.Timestamp(when)
    _, period = frozen_rule(cfg or {})
    periods = ((cfg or {}).get("source_rule_method") or {}).get("pak_age_periods", 3)
    max_age = float(periods) * period
    out = {}
    for tag in MEASURED_TAGS:
        out[tag] = None
        if tag not in signals.columns:
            continue
        series = signals[tag].loc[:when].dropna()
        if series.empty:
            continue
        at = series.index[-1]
        age = (when - at).total_seconds() / 60
        if age > max_age:
            continue
        out[tag] = {"value": float(series.iloc[-1]), "time": pd.Timestamp(at).isoformat(),
                    "age_min": round(age, 2), "max_age_min": max_age}
    return out


def load_response_model(root: Path) -> dict | None:
    """C2 `config/response_model.json`: нет файла → None; битый или не по схеме → ValueError."""
    path = Path(root) / RESPONSE_FILE
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Модель отклика {path} не читается: {exc}") from exc
    return validate_response_model(value, str(path))


def _finite_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _pair(value) -> bool:
    return isinstance(value, (list, tuple)) and len(value) == 2 and all(_finite_number(v) for v in value)


def validate_response_model(value, where: str = RESPONSE_FILE) -> dict:
    if not isinstance(value, dict) or value.get("schema_version") != RESPONSE_SCHEMA_VERSION:
        raise ValueError(f"Модель отклика {where}: ожидается schema_version={RESPONSE_SCHEMA_VERSION!r}")
    if value.get("tag") != "ht.T6":
        raise ValueError(f"Модель отклика {where}: ожидается tag ht.T6, получено {value.get('tag')!r}")
    beta = value.get("beta_mgkg_per_c")
    if not _finite_number(beta) or beta >= 0:
        raise ValueError(f"Модель отклика {where}: beta_mgkg_per_c должна быть отрицательным числом")
    if not _pair(value.get("ci")) or not value["ci"][0] <= beta <= value["ci"][1]:
        raise ValueError(f"Модель отклика {where}: ci должен быть парой чисел, накрывающей beta")
    envelope = value.get("envelope_dt_c")
    if not _finite_number(envelope) or envelope <= 0:
        raise ValueError(f"Модель отклика {where}: envelope_dt_c должен быть положительным числом")
    for key in ("t6_range_c", "f9_range_tph", "weak_strong"):
        if key in value and value[key] is not None and not _pair(value[key]):
            raise ValueError(f"Модель отклика {where}: {key} должен быть парой чисел")
    flow_beta = value.get("flow_beta")
    if flow_beta is not None and not _finite_number(flow_beta):
        raise ValueError(f"Модель отклика {where}: flow_beta должен быть числом или null")
    onset = value.get("response_onset_hours", DEFAULT_ONSET_HOURS)
    if not _finite_number(onset) or not 0 <= onset <= CASE_MAX_LAG_HOURS:
        raise ValueError(f"Модель отклика {where}: response_onset_hours должен лежать в [0, {CASE_MAX_LAG_HOURS:g}] ч")
    share = value.get("horizon_response_share", DEFAULT_HORIZON_SHARE)
    if not _finite_number(share) or not 0 < share <= 1:
        raise ValueError(f"Модель отклика {where}: horizon_response_share должна лежать в (0, 1]")
    return value


def response_lag(response: dict) -> tuple[float, float]:
    """(onset hours, share of β credited within the case horizon) declared with the response model."""
    return (float(response.get("response_onset_hours", DEFAULT_ONSET_HOURS)),
            float(response.get("horizon_response_share", DEFAULT_HORIZON_SHARE)))


def _main_density(raw: dict, tank_id: str = "main") -> float:
    for tank in raw["tanks"]:
        if tank["tank_id"] == tank_id:
            density = (tank.get("properties") or {}).get("density_kgm3")
            if not isinstance(density, dict) or not _finite_number(density.get("value")) or density["value"] <= 0:
                raise LiveError(f"Резервуар {tank_id}: плотность не задана, расходы не пересчитываются")
            return float(density["value"])
    raise LiveError(f"Резервуар {tank_id} не описан в сценарии")


def _reading(measured: dict, tag: str) -> dict | None:
    item = measured.get(tag)
    if not isinstance(item, dict) or not _finite_number(item.get("value")):
        return None
    return item


def _in_range(value: float, bounds) -> bool:
    return not _pair(bounds) or bounds[0] <= value <= bounds[1]


def _control_missing_note(tag: str) -> str:
    return (f"Тег {tag}: измерение на момент решения отсутствует или устарело; уставка сценарная, "
            f"числовая уставка не предлагается")


def bind_measurements(raw: dict, measured: dict, derived: dict, response: dict | None, forecast: dict,
                      tank_id: str = "main") -> dict:
    """Ставит измерения тегов и отклик по данным в копию сценария (только для реального состояния).

    * `controls.ht_reactor_inlet_temp_c.current` = T6 (`measured`), `min/max` = T6 ∓ envelope C2
      (`derived`); без измерения, без C2 или вне области отклика — `min = max = current`, уставка
      не предлагается.
    * `controls.ht_feed_flow_m3h.current` = F9·1000/ρ (т/ч → м³/ч, `derived`); отклик по расходу
      в C2 не оценён, поэтому `min = max = current`.
    * `model`: reference = измерения, `conversion_per_degree = −β/S₀` (линеаризация
      exp(−kΔT) ≈ 1 + βΔT/S₀ при |ΔT| ≤ envelope), provenance `derived`; без C2 модель не меняется.
    * `response_lag_hours` = `response_onset_hours` C2 (`derived`, 3 ч: β — отклик через 3–8 ч), а в пределах
      горизонта кейса засчитывается не больше `horizon_response_share` хода (`model.horizon_response_share`,
      `model.horizon_response_until_hours`); без C2 или вне области задержка остаётся сценарной.
    * `tanks[main].inflow` = F26·ρ/1000 (м³/ч → т/ч); `policy.tank_level_window_hours` =
      inventory / inflow в [1, 72] — поэтому измерения ставятся ДО `bind_forecast`.
    """
    out = copy.deepcopy(raw)
    density = derived["density_kgm3"]
    if not _finite_number(density) or density <= 0:
        raise LiveError("Плотность для пересчёта расходов должна быть положительным числом")
    stage = out["stages"]["hydrotreating"]
    controls, model = stage["controls"], stage.setdefault("model", {})
    t6, f9, f26 = (_reading(measured, tag) for tag in MEASURED_TAGS)
    notes, warnings = [], []

    # --- температура входа Р-202 ---
    temp = controls["ht_reactor_inlet_temp_c"]
    envelope = response["envelope_dt_c"] if response else None
    in_region = (response is not None and t6 is not None
                 and _in_range(t6["value"], response.get("t6_range_c"))
                 and (f9 is None or _in_range(f9["value"], response.get("f9_range_tph"))))
    if t6 is None:
        current = float(temp["current"]["value"])
        temp["current"] = {"value": current, "unit": "°C", "source": "scenario",
                           "note": _control_missing_note("ht.T6")}
        temp["min"], temp["max"] = (_bound(current, "°C", "scenario", "измерение отсутствует, числовая уставка не предлагается")
                                    for _ in range(2))
        notes.append("ht.T6: измерение отсутствует")
    else:
        current = round(float(t6["value"]), 4)
        temp["current"] = {"value": current, "unit": "°C", "source": "measured",
                           "note": (f"Тег ht.T6, {t6['time']}, возраст {t6['age_min']:.0f} мин: последнее "
                                    f"не-NaN значение не старше {t6.get('max_age_min', 0):g} мин")}
        if response is None:
            temp["min"], temp["max"] = (_bound(current, "°C", "scenario", "отклик по данным не загружен; числовая уставка не предлагается")
                                        for _ in range(2))
            notes.append("отклик по данным не загружен")
        elif not in_region:
            temp["min"], temp["max"] = (_bound(current, "°C", "scenario", "установка вне области, где оценён отклик; числовая уставка не предлагается")
                                        for _ in range(2))
            notes.append(f"ht.T6={current:g} или ht.F9 вне области отклика {response.get('t6_range_c')} / {response.get('f9_range_tph')}")
            outside = [f"{tag} = {item['value']:g} {unit} вне {list(bounds)}"
                       for tag, item, unit, bounds in (("ht.T6", t6, "°C", response.get("t6_range_c")),
                                                       ("ht.F9", f9, "т/ч", response.get("f9_range_tph")))
                       if item is not None and not _in_range(item["value"], bounds)]
            warnings.append("Установка вне режима, в котором оценён отклик по данным (" + "; ".join(outside) +
                            "): возможен пуск, останов или нештатный режим. Совет по температуре не даётся; "
                            "проверки выполнены с текущими уставками.")
        else:
            temp["min"] = _bound(current - envelope, "°C", "derived", f"конверт исследования отклика: T6 − {envelope:g} °C")
            temp["max"] = _bound(current + envelope, "°C", "derived", f"конверт исследования отклика: T6 + {envelope:g} °C")

    # --- расход сырья: F9 т/ч → м³/ч через плотность ---
    flow = controls["ht_feed_flow_m3h"]
    if f9 is None:
        flow_current = float(flow["current"]["value"])
        flow["current"] = {"value": flow_current, "unit": "м3/ч", "source": "scenario",
                           "note": _control_missing_note("ht.F9")}
        flow_note = "измерение отсутствует, числовая уставка не предлагается"
        notes.append("ht.F9: измерение отсутствует")
    else:
        flow_current = round(float(f9["value"]) * 1000.0 / density, 4)
        flow["current"] = {"value": flow_current, "unit": "м3/ч", "source": "derived",
                           "note": (f"Тег ht.F9 (массовый расход сырья) {f9['value']:.1f} т/ч, {f9['time']}, "
                                    f"возраст {f9['age_min']:.0f} мин; м³/ч = F9·1000/ρ при ρ = {density:g} кг/м³ "
                                    f"(медиана ЛИМС ГО точка 2). Плотность сокращается в (F/F_ref)^0.7, поэтому "
                                    f"допущение ρ_сырья ≈ ρ_продукта на результат не влияет.")}
        flow_note = "отклик по расходу в исследовании не оценён; числовая уставка не предлагается"
    flow["min"], flow["max"] = (_bound(flow_current, "м3/ч", "scenario", flow_note) for _ in range(2))
    flow.setdefault("actuation", {})
    flow["actuation"] = {**flow["actuation"], "measured_tag": "ht.F9",
                         "note": ((flow["actuation"].get("note") or "") +
                                  " Для привязки измерений используется ht.F9 (массовый расход, т/ч), "
                                  "а не F15 с неподтверждённым масштабом.").strip()}

    # --- модель отклика ---
    # Отношение отклика умножает серу притока, а приток — верхняя граница прогноза (bind_forecast),
    # поэтому линеаризуем в ней же; иначе наклон в плане был бы β·upper/value вместо β.
    s0 = forecast.get("upper")
    if response is not None and in_region and _finite_number(s0) and s0 > 0:
        beta = float(response["beta_mgkg_per_c"])
        model.update({
            "reference_temp_c": current,
            "reference_space_velocity_m3h": flow_current,
            "provenance": "derived",
            "beta_mgkg_per_c": beta,
            "beta_ci": list(response["ci"]),
            "weak_strong": list(response["weak_strong"]) if _pair(response.get("weak_strong")) else None,
            "envelope_dt_c": float(envelope),
            "response_source": RESPONSE_FILE,
            "response_tau": response.get("tau"),
            "response_rows": response.get("n_rows"),
            "source": "derived",
        })
        linearize_response(model, float(s0), "верхняя граница прогноза")
        onset, share = response_lag(response)
        horizon = float((out.get("horizon") or {}).get("hours") or 0.0)
        stage["response_lag_hours"] = {
            "value": onset, "unit": "ч", "source": "derived",
            "note": (f"Исследование отклика ({RESPONSE_FILE}): β — средний накопленный отклик через 3–8 ч на устойчивый "
                     f"шаг T6, поэтому эффект не засчитывается раньше {onset:g} ч; в пределах горизонта {horizon:g} ч "
                     f"засчитывается не больше {share:.0%} хода (регулятор доводит 0.62–0.66 заданного шага к 3 ч). "
                     f"Сценарное значение {float(stage['response_lag_hours']['value']):g} ч заменено.")}
        model["horizon_response_share"] = share
        model["horizon_response_until_hours"] = horizon
    else:
        model["provenance"] = "scenario"
        model["note"] = ((model.get("note") or "") + " Отклик по данным не загружен или неприменим: "
                         "коэффициенты сценарные." ).strip()
        if response is None:
            notes.append("отклик по данным не загружен")

    # --- приток резервуара и окно обновления ---
    for tank in out["tanks"]:
        if tank["tank_id"] != tank_id:
            continue
        if f26 is not None:
            inflow = round(float(f26["value"]) * density / 1000.0, 4)
            tank["inflow"] = {"value": inflow, "unit": "т/ч", "source": "derived",
                              "note": (f"Тег ht.F26 (расход гидроочищенного ДТ в цех №8) {f26['value']:.1f} м³/ч, "
                                       f"{f26['time']}, возраст {f26['age_min']:.0f} мин; т/ч = F26·ρ/1000 при "
                                       f"ρ = {density:g} кг/м³.")}
        else:
            notes.append("ht.F26: измерение отсутствует, приток сценарный")
        inflow_value = float(tank["inflow"]["value"])
        inventory = float(tank["inventory"]["value"])
        if inflow_value <= 0:
            raise LiveError("Приток резервуара должен быть положительным для расчёта окна обновления")
        window = min(72.0, max(1.0, inventory / inflow_value))
        policy = out.setdefault("policy", {})
        policy["tank_level_window_hours"] = round(window, 4)
        policy["tank_level_window_note"] = (f"Окно обновления = запас / приток = {inventory:g} т / {inflow_value:g} т/ч "
                                            f"= {inventory / inflow_value:.2f} ч, ограничено [1, 72] ч.")
        break
    else:
        raise LiveError(f"Резервуар {tank_id} не описан в сценарии")
    out["measurement_binding"] = {"tags": {tag: measured.get(tag) for tag in MEASURED_TAGS},
                                  "density_kgm3": density, "response_loaded": response is not None,
                                  "notes": notes, "warnings": warnings}
    return out


def linearize_response(model: dict, s0: float, basis: str) -> None:
    """k = −β/S₀ в точке S₀ — той сере притока, к которой план применяет отношение exp(−kΔT).

    Тогда наклон в плане при ΔT → 0 равен β независимо от уровня S₀.
    """
    beta, envelope = float(model["beta_mgkg_per_c"]), float(model["envelope_dt_c"])
    model["conversion_per_degree"] = -beta / s0
    model["linearization_sulfur_mgkg"] = s0
    model["note"] = (f"Отклик по данным ({model.get('response_source')}, τ={model.get('response_tau')}, "
                     f"{model.get('response_rows')} строк): β = {beta:g} мг/кг на °C, ДИ {model.get('beta_ci')}. "
                     f"k = −β/S₀ при S₀ = {s0:.3f} мг/кг ({basis}; к ней план применяет отклик): "
                     f"линеаризация exp(−kΔT) ≈ 1 + βΔT/S₀ при |ΔT| ≤ {envelope:g} °C. "
                     f"Опорные точки — измерения T6 и F9 на момент решения.")


def _bound(value: float, unit: str, source: str, note: str) -> dict:
    return {"value": round(float(value), 4), "unit": unit, "source": source, "note": note}


def interval_coverage(out: Path, bundle: dict) -> dict:
    """Заявленное покрытие интервала и фактическое на тесте 2026 для выбранной модели (metrics.json)."""
    result = {}
    target = (bundle.get("config") or {}).get("interval_coverage")
    if _finite_number(target):
        result["coverage_target"] = float(target)
    path = Path(out) / "metrics.json"
    if path.exists():
        metrics = json.loads(path.read_text(encoding="utf-8"))
        test = ((metrics.get("models") or {}).get(bundle.get("selected")) or {}).get("test") or {}
        if _finite_number(test.get("interval_coverage")):
            result["coverage_test"] = float(test["interval_coverage"])
    return result


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
    state["origin"] = MEASURED_ORIGIN
    state.update(recent_quality_history(lab, online, when, bundle["config"]))
    state["measurements"] = measurements_at(signals, when, bundle["config"])
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
    trusted analyser readings in that window. Readings inside a flat run of at least `pak_frozen_readings`
    identical values are not trusted. With too few trusted readings the laboratory mean in the window is used (at least two
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


def frozen_analyser_hold(raw: dict, state: dict) -> dict | None:
    """What the inflow may not fall below while the analyser is frozen.

    A frozen analyser removes the most recent evidence, and the fallback model without it may read
    lower than what was last measured. Until a laboratory result arrives the last trusted analyser
    reading stands; a laboratory result sampled after it is the control fact instead.
    """
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
                # Вклад притока за горизонт кейса при полном перемешивании: ΔS = (S_in − S_tank)·(1 − exp(−q·3/M)).
                q, mass = float(tank["inflow"]["value"]), float(tank["inventory"]["value"])
                if q > 0 and mass > 0:
                    shift = (inflow - level["value"]) * (1 - math.exp(-q * 3.0 / mass))
                    note += (f" Вклад прогноза за 3 ч: {shift:+.3f} мг/кг к сере резервуара "
                             f"(приток {q:g} т/ч, запас {mass:g} т).")
            tank["inflow_sulfur_mgkg"] = {"value": round(inflow, 4), "unit": "мг/кг", "source": "derived",
                                          "note": note}
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
    decision_factory: object | None = None
    #: Строит проверку устойчивости на СВЯЗАННОМ сценарии (после привязки прогноза и измерений).
    robustness_factory: Callable | None = None
    #: Содержимое C2 (`load_response_model`) или None — тогда модель отклика остаётся сценарной.
    response_model: dict | None = None
    #: Покрытие интервала (цель и факт на тесте) — см. `interval_coverage(out, bundle)`.
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
