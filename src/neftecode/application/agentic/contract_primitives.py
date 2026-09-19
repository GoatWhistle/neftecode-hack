import json
import math
import re

VERDICTS = ("ACCEPT", "REVISE", "REJECT", "UNKNOWN")
RISK_LEVELS = ("low", "medium", "high", "unknown")
FINAL_ACTIONS = ("select", "keep_legacy", "refuse")
ROLES = ("orchestrator", "quality", "reliability")

_CODE = re.compile(r"^[a-z0-9_]{1,40}$")
_CANDIDATE = re.compile(r"^[A-Za-z0-9_:,.\-]{1,80}$")

MAX_REASONS = 6
MAX_REASON_TEXT = 300
MAX_CONSTRAINTS = 4
MAX_PREFERRED = 3
MAX_CANDIDATE_VERDICTS = 5
MAX_EVIDENCE = 10
MAX_REQUESTED_CHECKS = 5
MAX_SUMMARY = 400

MARGIN_RANGES = {
    "sulfur_mgkg": (0.0, 5.0),
    "t95_c": (0.0, 20.0),
    "cetane_number": (0.0, 5.0),
    "density_min_kgm3": (0.0, 15.0),
    "density_max_kgm3": (0.0, 15.0),
}

CONSTRAINT_TYPES = {
    "min_quality_margin": (True, "number", None),
    "max_changes": (False, "int", (0, 2)),
    "forbid_additive": (False, None, None),
    "max_outflow_utilization": (False, "number", (0.3, 1.0)),
    "constant_plans_only": (False, None, None),
    "min_hours_to_violation": (False, "number", (0.0, 48.0)),
    "require_not_fragile": (False, None, None),
}


class ContractViolation(ValueError):

    def __init__(self, path: str, message: str):
        super().__init__(f"{path}: {message}")
        self.path = path


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _text(value, path: str, limit: int) -> str:
    if not isinstance(value, str):
        raise ContractViolation(path, "ожидается строка")
    return value.strip()[:limit]


def _code(value, path: str) -> str:
    if not isinstance(value, str) or not _CODE.match(value):
        raise ContractViolation(path, "код причины: [a-z0-9_]{1,40}")
    return value


def _list(value, path: str, limit: int) -> list:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ContractViolation(path, "ожидается список")
    return value[:limit]


def _object(raw, path: str, allowed: set[str], required: set[str]) -> dict:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ContractViolation(path, f"не JSON: {exc.msg}") from exc
    if not isinstance(raw, dict):
        raise ContractViolation(path, "ожидается JSON-объект")
    extra = sorted(set(raw) - allowed)
    if extra:
        raise ContractViolation(path, f"неизвестные поля {extra}")
    missing = sorted(required - set(raw))
    if missing:
        raise ContractViolation(path, f"нет обязательных полей {missing}")
    return raw


def extract_json_object(text: str) -> dict | None:
    if not isinstance(text, str):
        return None
    stripped = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        value = json.loads(stripped)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        pass
    decoder, found, index = json.JSONDecoder(), [], 0
    while True:
        start = stripped.find("{", index)
        if start < 0:
            break
        try:
            value, end = decoder.raw_decode(stripped, start)
        except json.JSONDecodeError:
            index = start + 1
            continue
        if isinstance(value, dict):
            found.append(value)
        index = end
    return found[0] if len(found) == 1 else None
