import ast
from dataclasses import dataclass
import re

import numpy as np
import pandas as pd

CORRECTED = {
    "24-2000:GODT:T90": "162.998 + 0.12945*T12 + 59.57*(F15/2000) + 0.00036*W7 + 0.26366*T23 - 424.72638*F1/F26",
    "24-2000:GODT:T50": "44.625 + 10.0224*P13 + 0.06981*F9 + 0.471*T6",
    "24-2000:GODT:CloudPoint": "0.0002*F22 + 0.0021*W7 + 0.00008*F25 - 0.30656*F1 + 0.12018*T6 "
                               "+ 0.01916*F9 - 48.254 - 0.05249*T16 + 0.00011",
    "24-2000:GODT:CFPP": "0.22088*T23 - 102.375 - 47.75834*P8 + 0.03862*F9 + 43.60207*W7 + 43.81849*P24",
    "24-2000:GODT:T95": "0.03814*F9 - 9.201 - 0.00002*F2 + 0.50*T6 + 0.48321*LIMSPipelineTninetyfive",
}

AVT_CFPP_FIX = "31.40363 - 0.06784*T33 + 17.411*P67 - 8.11544*P4 - 0.47309*F65/(F32 + F30)"

PUBLISHED_2026_09_16 = {
    "AVT6:240-350:D15": "791.22872 - 5.30294*(F65/(F32 + F30)) + 0.52755*T66 - 0.15629*T33",
    "AVT6:240-350:CFPP": AVT_CFPP_FIX,
    "AVT6:350:T50": "493.6798 + 1.281193*T42 - 0.955342*T48 - 0.018454*F31 + 0.265904*F57 - 0.082047*T66 "
                    "- 0.545083*T33",
    "AVT6:350:I350": "39.562 - 1.62865*L43 + 0.76664*T6 - 0.22361*T18 + 0.00031*F64*(T15 - T11)",
}

UNBOUND_LAB_INPUTS = {
    "LIMSPipelineDensity15": "LIMS:24-2000.Pipeline.D15",
    "LIMSPipelineTninetyfive": "LIMS:24-2000.Pipeline.95%.T",
}

UNIT_PREFIX = {"AVT6": "avt", "24-2000": "ht"}

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

AVT_LAB_BINDING = {
    "AVT6:240-350:D15": ("avt_3", "D15"),
    "AVT6:240-350:T50": ("avt_3", "50%.T"),
    "AVT6:240-350:EBP": ("avt_3", "EBP.T"),
    "AVT6:240-350:CFPP": ("avt_3", "FilterabilityLimit.T"),
    "AVT6:350:T50": ("avt_1", "50%.T"),
    "AVT6:350:I350": ("avt_1", "I350"),
    "AVT6:350:D15": ("avt_1", "D15"),
    "AVT6:350:CFPP": ("avt_1", "CFPP"),
}

AVT_BINDING_RULE = ("Группа 240-350 — точка ЛИМС АВТ 3 (конечный выход ДТ), группа 350 — точка 1 "
                    "(единственная с I350, в листе ЛА «до 350»). Привязка выбрана по положению точки "
                    "в процессе до сверки и остаётся гипотезой: организаторы её не подтверждали.")

_ALLOWED_NODES = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Add, ast.Sub, ast.Mult, ast.Div,
                  ast.USub, ast.UAdd, ast.Constant, ast.Name, ast.Load)


class VakError(ValueError):
    pass


def normalise(text: str) -> str:
    if not isinstance(text, str) or not text.strip():
        raise VakError("Пустой текст формулы")
    out = text.strip()
    for identifier, reference in UNBOUND_LAB_INPUTS.items():
        out = out.replace(reference, identifier)
    out = re.sub(r"(?<=\d),(?=\d)", ".", out)
    out = re.sub(r"(?<=[\d\)])\s*[xх]\s*(?=[A-Za-zА-Яа-я\(\d])", "*", out)
    out = re.sub(r"\s+", " ", out)
    return out


def _balance(text: str) -> str:
    depth = 0
    kept = []
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            if depth == 0:
                continue
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
        return not self.unbound

    def to_dict(self) -> dict:
        return {"name": self.name, "group": self.group, "expression": self.expression,
                "inputs": list(self.inputs), "unbound": list(self.unbound),
                "corrected": self.corrected, "computable": self.computable,
                "ratios": list(self.ratios)}


def telemetry_prefix(name: str) -> str:
    return "ht" if name.startswith("24-2000") else "avt"


def _collect(node, names: set):
    if not isinstance(node, _ALLOWED_NODES):
        raise VakError(f"Недопустимая конструкция в формуле: {type(node).__name__}")
    if isinstance(node, ast.Name):
        names.add(node.id)
    for child in ast.iter_child_nodes(node):
        _collect(child, names)


def _ratios(expression: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(f"{a}/{b}" for a, b in
                               re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\s*/\s*([A-Za-z_][A-Za-z0-9_]*)", expression)))


def parse_formula(name: str, text: str, group: str) -> Formula:
    corrected = name in CORRECTED or name in PUBLISHED_2026_09_16
    source = PUBLISHED_2026_09_16.get(name, CORRECTED.get(name, text))
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
        safe = np.where(np.abs(right) < 1e-9, np.nan, right)
        with np.errstate(divide="ignore", invalid="ignore"):
            return left / safe
    raise VakError(f"Недопустимая операция {type(node.op).__name__}")
