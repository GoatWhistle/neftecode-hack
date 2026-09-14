"""Virtual analysers: parse the 17 published formulas, apply the expert's corrections, check them.

The sheet mixes decimal commas with points and uses `x` where `*` is meant, so the text is
normalised before parsing. Parsing goes through Python's own expression grammar restricted to
arithmetic over named tags: no attribute access, no calls, no names outside the tag map.

What a formula is and is not:

* it is a published dependency, usable as a calculated feature and as a fallback estimate;
* it is **not** evidence of causality. The sign of a coefficient does not authorise moving
  that tag. See context/idea-review.md, section 2.

A formula whose inputs cannot be bound — the two `LIMS:24-2000.Pipeline...` references have no
declared laboratory point — reports explicit unavailability instead of a number.
"""
import ast
from dataclasses import dataclass, field
import math
import re

import numpy as np
import pandas as pd

#: Corrections published by the expert (message 517). Only these five were corrected.
CORRECTED = {
    "24-2000:GODT:T90": "162.998 + 0.12945*T12 + 59.57*(F15/2000) + 0.00036*W7 + 0.26366*T23 - 424.72638*F1/F26",
    "24-2000:GODT:T50": "44.625 + 10.0224*P13 + 0.06981*F9 + 0.471*T6",
    "24-2000:GODT:CloudPoint": "0.0002*F22 + 0.0021*W7 + 0.00008*F25 - 0.30656*F1 + 0.12018*T6 "
                               "+ 0.01916*F9 - 48.254 - 0.05249*T16 + 0.00011",
    "24-2000:GODT:CFPP": "0.22088*T23 - 102.375 - 47.75834*P8 + 0.03862*F9 + 43.60207*W7 + 43.81849*P24",
    "24-2000:GODT:T95": "0.03814*F9 - 9.201 - 0.00002*F2 + 0.50*T6 + 0.48321*LIMSPipelineTninetyfive",
}

#: The AVT CFPP text carries one closing bracket too many. The expert fixed the ending to
#: `F65/F32 + F30`; turning it into `F65/(F32+F30)` on our own is explicitly forbidden.
AVT_CFPP_FIX = "31.40363 - 0.06784*T33 + 17.411*P67 - 8.11544*P4 - 0.47309*(F65/F32 + F30)"

#: Laboratory inputs with no declared sampling point. Formulas needing them cannot be computed.
#: Identifiers deliberately carry no digits next to underscores: the punctuation
#: normalisation below rewrites `<digit>_<digit>` back into a decimal point.
UNBOUND_LAB_INPUTS = {
    "LIMSPipelineDensity15": "LIMS:24-2000.Pipeline.D15",
    "LIMSPipelineTninetyfive": "LIMS:24-2000.Pipeline.95%.T",
}

#: Which telemetry file supplies the short tags of each formula group.
UNIT_PREFIX = {"AVT6": "avt", "24-2000": "ht"}

#: Laboratory column matching each 24-2000 virtual analyser, at hydrotreating sampling point 2.
#: The expert confirmed that point for the online sulfur analyser (message 517).
GODT_LAB_COLUMN = {
    "24-2000:GODT:T90": "90%.T",
    "24-2000:GODT:T50": "50%.T",
    "24-2000:GODT:I250": "I250",
    "24-2000:GODT:D15": "D15",
    "24-2000:GODT:CloudPoint": "CloudPoint",
    "24-2000:GODT:T95": "95%.T",
    "24-2000:GODT:CFPP": "CFPP",
    "24-2000:GODT:IBP": "IBP.T",
}

_ALLOWED_NODES = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Add, ast.Sub, ast.Mult, ast.Div,
                  ast.USub, ast.UAdd, ast.Constant, ast.Name, ast.Load)


class VakError(ValueError):
    """Raised when a formula cannot be parsed or bound, with the offending text."""


def normalise(text: str) -> str:
    """Bring one sheet cell to a single arithmetic notation without changing its meaning."""
    if not isinstance(text, str) or not text.strip():
        raise VakError("Пустой текст формулы")
    out = text.strip()
    # Bind the laboratory references first: they contain characters the arithmetic
    # normalisation below would mangle into an invalid literal.
    for identifier, reference in UNBOUND_LAB_INPUTS.items():
        out = out.replace(reference, identifier)
    # Decimal comma only between digits; a comma elsewhere would be a separator we must not eat.
    out = re.sub(r"(?<=\d),(?=\d)", ".", out)
    # `x` is used for multiplication between an operand and a following term.
    out = re.sub(r"(?<=[\d\)])\s*[xх]\s*(?=[A-Za-zА-Яа-я\(\d])", "*", out)
    out = re.sub(r"\s+", " ", out)
    return out


def _balance(text: str) -> str:
    """Drop the single unmatched closing bracket rather than guessing a new grouping."""
    depth = 0
    kept = []
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            if depth == 0:
                continue  # unmatched: the expert's fix removes it
            depth -= 1
        kept.append(ch)
    if depth:
        raise VakError(f"Незакрытые скобки в формуле: {text}")
    return "".join(kept)


@dataclass(frozen=True)
class Formula:
    name: str
    group: str
    text: str
    expression: str
    inputs: tuple[str, ...]
    unbound: tuple[str, ...]
    corrected: bool
    ratios: tuple[str, ...] = ()

    @property
    def computable(self) -> bool:
        """A formula needing an unbound laboratory point yields unavailability, not a number."""
        return not self.unbound

    def to_dict(self) -> dict:
        return {"name": self.name, "group": self.group, "expression": self.expression,
                "inputs": list(self.inputs), "unbound": list(self.unbound),
                "corrected": self.corrected, "computable": self.computable,
                "ratios": list(self.ratios)}


def telemetry_prefix(name: str) -> str:
    """Which telemetry file a formula's short tags come from."""
    return "ht" if name.startswith("24-2000") else "avt"


def _collect(node, names: set):
    if not isinstance(node, _ALLOWED_NODES):
        raise VakError(f"Недопустимая конструкция в формуле: {type(node).__name__}")
    if isinstance(node, ast.Name):
        names.add(node.id)
    for child in ast.iter_child_nodes(node):
        _collect(child, names)


def _ratios(expression: str) -> tuple[str, ...]:
    """Ratios appearing in the published formulas are candidate features in their own right."""
    return tuple(dict.fromkeys(f"{a}/{b}" for a, b in
                               re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\s*/\s*([A-Za-z_][A-Za-z0-9_]*)", expression)))


def parse_formula(name: str, text: str, group: str) -> Formula:
    corrected = name in CORRECTED
    source = CORRECTED.get(name, AVT_CFPP_FIX if name == "AVT6:240-350:CFPP" else text)
    expression = _balance(normalise(source))
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise VakError(f"{name}: не разбирается «{expression}» — {exc}") from exc
    names: set[str] = set()
    _collect(tree.body, names)
    unbound = tuple(sorted(n for n in names if n in UNBOUND_LAB_INPUTS))
    inputs = tuple(sorted(n for n in names if n not in UNBOUND_LAB_INPUTS))
    return Formula(name, group, str(text), expression, inputs, unbound, corrected, _ratios(expression))


def evaluate(formula: Formula, frame: pd.DataFrame, *, prefix: str | None = None) -> np.ndarray:
    """Evaluate on aligned telemetry. Division guards against a vanishing denominator."""
    if not formula.computable:
        raise VakError(f"{formula.name}: не вычисляется, не привязаны входы "
                       f"{', '.join(UNBOUND_LAB_INPUTS[u] for u in formula.unbound)}")
    prefix = prefix or telemetry_prefix(formula.name)
    values = {}
    missing = []
    for tag in formula.inputs:
        column = f"{prefix}.{tag}"
        if column not in frame.columns:
            missing.append(column)
        else:
            values[tag] = frame[column].to_numpy(float)
    if missing:
        raise VakError(f"{formula.name}: в телеметрии нет тегов {', '.join(missing)}")
    return _eval_node(ast.parse(formula.expression, mode="eval").body, values, len(frame))


def _eval_node(node, values, size):
    if isinstance(node, ast.Constant):
        return np.full(size, float(node.value))
    if isinstance(node, ast.Name):
        return values[node.id]
    if isinstance(node, ast.UnaryOp):
        inner = _eval_node(node.operand, values, size)
        return -inner if isinstance(node.op, ast.USub) else inner
    left = _eval_node(node.left, values, size)
    right = _eval_node(node.right, values, size)
    if isinstance(node.op, ast.Add):
        return left + right
    if isinstance(node.op, ast.Sub):
        return left - right
    if isinstance(node.op, ast.Mult):
        return left * right
    if isinstance(node.op, ast.Div):
        # A denominator near zero produces unknown, never a huge number that looks like a reading.
        safe = np.where(np.abs(right) < 1e-9, np.nan, right)
        with np.errstate(divide="ignore", invalid="ignore"):
            return left / safe
    raise VakError(f"Недопустимая операция {type(node.op).__name__}")


@dataclass
class FormulaCheck:
    """Result of comparing one formula with the laboratory on the same samples."""

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

    def to_dict(self) -> dict:
        return {"name": self.name, "status": self.status, "n": self.n, "mae": self.mae,
                "bias": self.bias, "correlation": self.correlation, "lab_column": self.lab_column,
                "applicable_from": self.first_sample, "applicable_to": self.last_sample,
                "reason": self.reason, "limitations": list(self.limitations)}


CAUSALITY_NOTE = ("Формула — опубликованная зависимость, а не доказательство причинности. "
                  "Знак коэффициента не разрешает управлять этим тегом.")


def check_formula(formula: Formula, signals: pd.DataFrame, lab: pd.DataFrame,
                  tolerance_minutes: int = 30) -> FormulaCheck:
    """Compare a formula with the laboratory series it is supposed to reproduce."""
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
        correlation=None if correlation is None or not math.isfinite(correlation) else correlation,
        lab_column=GODT_LAB_COLUMN.get(formula.name),
        first_sample=str(times[good][0]), last_sample=str(times[good][-1]),
        reason="Сверено с лабораторией на общих пробах",
        limitations=(CAUSALITY_NOTE,
                     "Период построения коэффициентов формулы неизвестен: нельзя считать её "
                     "независимой от нашего тестового периода.",
                     "Ошибка считается на пробах, совпавших по времени в пределах "
                     f"{tolerance_minutes} минут."))


def ratio_features(formulas: dict[str, Formula], signals: pd.DataFrame, prefix_of=None) -> pd.DataFrame:
    """Ratios the published formulas rely on, offered as features with denominator protection."""
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


def check_all(formula_rows, lab: dict[str, pd.DataFrame], signals: pd.DataFrame) -> dict:
    """Run every published formula against the laboratory and report the outcome of each."""
    formulas = {name: parse_formula(name, source, group)
                for name, source, group in formula_rows}
    checks = []
    for name, formula in formulas.items():
        column = GODT_LAB_COLUMN.get(name)
        checks.append(check_formula(formula, signals, lab.get(column) if column else None).to_dict())
    by_status: dict[str, int] = {}
    for check in checks:
        by_status[check["status"]] = by_status.get(check["status"], 0) + 1
    # Passing a correlation threshold is not adoption: nothing in the decision path takes a
    # quality value from a virtual analyser, and none of the three required product properties
    # is obtainable from one.
    above_threshold = [c["name"] for c in checks
                       if c["status"] == "checked" and (c["correlation"] or 0) >= 0.5]
    return {
        "formulas": {name: f.to_dict() for name, f in formulas.items()},
        "checks": checks,
        "summary": by_status,
        "passed_correlation_threshold": above_threshold,
        "used_as_quality_estimate": [],
        "adoption_rule": "Формула считается пригодной только если она даёт значение одного из "
                         "требуемых показателей продукта и согласуется с лабораторией. Ни одна "
                         "не удовлетворяет обоим условиям, поэтому источником значения качества "
                         "не служит ни одна: ВАК имеет низший приоритет источника по ТЗ.",
        "lab_point": "Гидроочистка, точка отбора 2 (та же точка, что подтверждена экспертом для ПАК-серы)",
        "notes": [
            "Формулы АВТ не сверялись: соответствие их фракций конкретной лабораторной точке в пакете "
            "не задано, и подбирать точку по лучшему совпадению значило бы выбрать её по результату.",
            CAUSALITY_NOTE,
            "Период построения коэффициентов формул неизвестен; независимость от нашего тестового "
            "периода не гарантирована.",
        ],
    }
