from dataclasses import dataclass, field
import math

import numpy as np
import pandas as pd

from .vak_formulas import (AVT_BINDING_RULE, AVT_CFPP_FIX, AVT_LAB_BINDING, CORRECTED, Formula, GODT_LAB_COLUMN,
                           PUBLISHED_2026_09_16, UNBOUND_LAB_INPUTS, UNIT_PREFIX, VakError, evaluate, normalise,
                           parse_formula, telemetry_prefix)

__all__ = ["AVT_BINDING_RULE", "AVT_CFPP_FIX", "AVT_LAB_BINDING", "CAUSALITY_NOTE", "CORRECTED", "Formula",
           "FormulaCheck", "GODT_LAB_COLUMN", "PUBLISHED_2026_09_16", "UNBOUND_LAB_INPUTS", "UNIT_PREFIX",
           "VakError", "check_all", "check_formula", "evaluate", "input_locations", "normalise",
           "parse_formula", "ratio_features", "telemetry_prefix"]


@dataclass
class FormulaCheck:

    name: str
    status: str
    n: int = 0
    mae: float | None = None
    bias: float | None = None
    correlation: float | None = None
    lab_column: str | None = None
    first_sample: str | None = None
    last_sample: str | None = None
    reason: str = ""
    limitations: tuple[str, ...] = field(default_factory=tuple)
    lab_point: str | None = None
    binding: str | None = None
    median_reference_mae: float | None = None

    def to_dict(self) -> dict:
        return {"name": self.name, "status": self.status, "n": self.n, "mae": self.mae,
                "bias": self.bias, "correlation": self.correlation, "lab_column": self.lab_column,
                "lab_point": self.lab_point, "binding": self.binding,
                "median_reference_mae": self.median_reference_mae,
                "applicable_from": self.first_sample, "applicable_to": self.last_sample,
                "reason": self.reason, "limitations": list(self.limitations)}


CAUSALITY_NOTE = ("Формула — опубликованная зависимость, а не доказательство причинности. "
                  "Знак коэффициента не разрешает управлять этим тегом.")


def check_formula(formula: Formula, signals: pd.DataFrame, lab: pd.DataFrame,
                  tolerance_minutes: int = 30, lab_column: str | None = None,
                  lab_point: str | None = None, binding: str | None = None) -> FormulaCheck:
    result = _check_formula(formula, signals, lab, tolerance_minutes)
    result.lab_column = lab_column or result.lab_column
    result.lab_point, result.binding = lab_point, binding
    if binding == "hypothesis_by_process_position":
        result.limitations = result.limitations + (AVT_BINDING_RULE,)
    return result


def _check_formula(formula: Formula, signals: pd.DataFrame, lab: pd.DataFrame,
                   tolerance_minutes: int) -> FormulaCheck:
    if not formula.computable:
        names = ", ".join(UNBOUND_LAB_INPUTS[u] for u in formula.unbound)
        return FormulaCheck(formula.name, "unavailable",
                            reason=f"Вход {names} не привязан к лабораторной точке; расчёт не выполняется",
                            limitations=(CAUSALITY_NOTE,))
    if lab is None or lab.empty:
        return FormulaCheck(formula.name, "unchecked",
                            reason="Нет лабораторного ряда для сверки этого показателя",
                            limitations=(CAUSALITY_NOTE,))
    try:
        computed = evaluate(formula, signals)
    except VakError as exc:
        return FormulaCheck(formula.name, "unavailable", reason=str(exc), limitations=(CAUSALITY_NOTE,))
    series = pd.Series(computed, index=signals.index)
    times = pd.DatetimeIndex(lab.time)
    aligned = series.reindex(times, method="nearest", tolerance=pd.Timedelta(value=tolerance_minutes, unit="m"))
    actual = pd.Series(lab.value.to_numpy(float), index=times)
    good = aligned.notna() & actual.notna() & np.isfinite(aligned.to_numpy()) & np.isfinite(actual.to_numpy())
    n = int(good.sum())
    if n < 30:
        return FormulaCheck(formula.name, "unchecked", n=n,
                            reason=f"Совпало лишь {n} проб; для честной оценки ошибки этого мало",
                            limitations=(CAUSALITY_NOTE,))
    a, b = actual[good].to_numpy(), aligned[good].to_numpy()
    correlation = float(np.corrcoef(a, b)[0, 1]) if np.std(a) > 0 and np.std(b) > 0 else None
    return FormulaCheck(
        formula.name, "checked", n=n, mae=float(np.abs(a - b).mean()), bias=float((b - a).mean()),
        median_reference_mae=float(np.abs(a - np.median(a)).mean()),
        correlation=None if correlation is None or not math.isfinite(correlation) else correlation,
        lab_column=GODT_LAB_COLUMN.get(formula.name),
        first_sample=str(times[good][0]), last_sample=str(times[good][-1]),
        reason="Сверено с лабораторией на общих пробах",
        limitations=(CAUSALITY_NOTE,
                     "Период построения коэффициентов формулы неизвестен: нельзя считать её "
                     "независимой от нашего тестового периода.",
                     "Ошибка считается на пробах, совпавших по времени в пределах "
                     f"{tolerance_minutes} минут.",
                     "median_reference_mae — ошибка постоянной медианы тех же проб; она подсмотрена "
                     "на них же и служит только масштабом, а не соперником-моделью."))


def ratio_features(formulas: dict[str, Formula], signals: pd.DataFrame, prefix_of=None) -> pd.DataFrame:
    out = {}
    for formula in formulas.values():
        prefix = telemetry_prefix(formula.name)
        for ratio in formula.ratios:
            numerator, denominator = ratio.split("/")
            a, b = f"{prefix}.{numerator}", f"{prefix}.{denominator}"
            if a in signals.columns and b in signals.columns:
                bottom = signals[b].to_numpy(float)
                with np.errstate(divide="ignore", invalid="ignore"):
                    out[f"vak.{prefix}.{numerator}_over_{denominator}"] = np.where(
                        np.abs(bottom) < 1e-9, np.nan, signals[a].to_numpy(float) / bottom)
    return pd.DataFrame(out, index=signals.index)


def input_locations(formula: Formula, tag_map: dict[str, dict]) -> dict:
    if telemetry_prefix(formula.name) != "avt":
        return {"locations": {}, "columns": [], "unmapped": [],
                "note": "Схем 24-2000 нет: расположение входов не известно"}
    locations, unmapped = {}, []
    for tag in formula.inputs:
        entry = tag_map.get(tag)
        if entry is None:
            unmapped.append(tag)
            continue
        locations[tag] = {"column": entry["column"], "place": entry["place"],
                          "controlled_by_legend": entry["controlled_by_legend"]}
    return {"locations": locations,
            "columns": sorted({item["column"] for item in locations.values()}),
            "unmapped": unmapped,
            "note": "Расположение по схемам АВТ 14.09; не подтверждение единиц и управляемости"}


def check_all(formula_rows, lab: dict[str, pd.DataFrame], signals: pd.DataFrame,
              tag_map: dict[str, dict] | None = None,
              avt_lab: dict[str, dict[str, pd.DataFrame]] | None = None) -> dict:
    formulas = {name: parse_formula(name, source, group)
                for name, source, group in formula_rows}
    described = {name: f.to_dict() for name, f in formulas.items()}
    if tag_map is not None:
        for name, formula in formulas.items():
            described[name]["input_locations"] = input_locations(formula, tag_map)
    checks = []
    for name, formula in formulas.items():
        if name in GODT_LAB_COLUMN:
            column = GODT_LAB_COLUMN[name]
            check = check_formula(formula, signals, lab.get(column), lab_column=column,
                                  lab_point="hydrotreating_2", binding="confirmed_for_sulfur_analyser")
        elif name in AVT_LAB_BINDING and avt_lab is not None:
            point, column = AVT_LAB_BINDING[name]
            check = check_formula(formula, signals, avt_lab.get(point, {}).get(column),
                                  lab_column=column, lab_point=point,
                                  binding="hypothesis_by_process_position")
        else:
            check = check_formula(formula, signals, None)
        checks.append(check.to_dict())
    by_status: dict[str, int] = {}
    for check in checks:
        by_status[check["status"]] = by_status.get(check["status"], 0) + 1
    above_threshold = [c["name"] for c in checks
                       if c["status"] == "checked" and (c["correlation"] or 0) >= 0.5]
    return {
        "formulas": described,
        "checks": checks,
        "summary": by_status,
        "passed_correlation_threshold": above_threshold,
        "used_as_quality_estimate": [],
        "adoption_rule": "Формула считается пригодной только если она даёт значение одного из "
                         "требуемых показателей продукта и согласуется с лабораторией. Ни одна "
                         "не удовлетворяет обоим условиям, поэтому источником значения качества "
                         "не служит ни одна: ВАК имеет низший приоритет источника по ТЗ.",
        "lab_point": "Гидроочистка, точка отбора 2 (та же точка, что подтверждена экспертом для ПАК-серы)",
        "avt_binding": ({"rule": AVT_BINDING_RULE, "formulas": {k: list(v) for k, v in AVT_LAB_BINDING.items()}}
                        if avt_lab is not None else None),
        "notes": [
            ("Формулы АВТ сверены с точками ЛИМС АВТ по заранее объявленной гипотезе привязки; "
             "точку не подбирали по лучшему совпадению." if avt_lab is not None else
             "Формулы АВТ не сверялись: лабораторные ряды АВТ не переданы."),
            CAUSALITY_NOTE,
            "Период построения коэффициентов формул неизвестен; независимость от нашего тестового "
            "периода не гарантирована.",
        ],
    }
