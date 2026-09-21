import copy

import pandas as pd

from neftecode.infrastructure.data.data import frozen_rule
from neftecode.infrastructure.response.estimate import response_at

from .constants import LiveError, MEASURED_TAGS, RESPONSE_FILE, _bound, _finite_number, _pair
from .response_model import linearize_response, response_lag


def measurements_at(signals: pd.DataFrame, when, cfg: dict) -> dict:
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
                      tank_id: str = "main", at=None) -> dict:
    out = copy.deepcopy(raw)
    policy = out.setdefault("policy", {})
    disabled = set(policy.get("disabled_control_moves") or ())
    disabled.update(("crude_feed_rate_tph", "avt_furnace_outlet_temp_c"))
    policy["disabled_control_moves"] = sorted(disabled)
    policy["disabled_control_moves_note"] = (
        "В live-контуре ходы АВТ не предлагаются: время прохождения через промежуточные ёмкости и "
        "измеренный отклик товарного качества на эти ходы не подтверждены."
    )
    density = derived["density_kgm3"]
    if not _finite_number(density) or density <= 0:
        raise LiveError("Плотность для пересчёта расходов должна быть положительным числом")
    stage = out["stages"]["hydrotreating"]
    controls, model = stage["controls"], stage.setdefault("model", {})
    t6, f9, f26 = (_reading(measured, tag) for tag in MEASURED_TAGS)
    notes, warnings = [], []
    if response is not None and at is not None:
        selected = response_at(response, at)
        if selected is None:
            notes.append(f"оценки отклика, сделанной до {pd.Timestamp(at).isoformat()}, нет: отклик по данным не применяется")
        response = selected
    elif response is not None and response.get("estimates"):
        raise LiveError("Модель отклика с оценками по τ требует момента решения (at)")

    temp = controls["ht_reactor_inlet_temp_c"]
    envelope = response["envelope_dt_c"] if response else None
    in_region = (response is not None and t6 is not None
                 and _in_range(t6["value"], response.get("t6_range_c"))
                 and f9 is not None
                 and _in_range(f9["value"], response.get("f9_range_tph")))
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
        elif f9 is None:
            temp["min"], temp["max"] = (_bound(current, "°C", "scenario",
                                               "ход T6 не разрешён: ht.F9 не измерен (расход сырья ГО сценарный, "
                                               "не измеренный); область применимости отклика по T6 зависит от F9, "
                                               "числовая уставка не предлагается")
                                        for _ in range(2))
            notes.append("ход T6 не разрешён: ht.F9 не измерен")
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
            "note": (f"Ответ организаторов 18.09: коррекция начинает действовать через 0,5–2 ч; паспортного "
                     f"времени нет. Консервативно эффект не засчитывается раньше {onset:g} ч. Исследование "
                     f"{RESPONSE_FILE} оценивает редкое окно плато 3–8 ч; в пределах горизонта {horizon:g} ч "
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
