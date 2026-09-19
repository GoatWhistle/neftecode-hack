import math

MEASURED_TAGS = ("ht.T6", "ht.F9", "ht.F26")
RESPONSE_SCHEMA_VERSION = "v1"
RESPONSE_FILE = "artifacts/response_model.json"
DEFAULT_ONSET_HOURS = 2.0
DEFAULT_HORIZON_SHARE = 1.0
CASE_MAX_LAG_HOURS = 3.0


class LiveError(ValueError):
    pass


def _finite_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _pair(value) -> bool:
    return isinstance(value, (list, tuple)) and len(value) == 2 and all(_finite_number(v) for v in value)


def _bound(value: float, unit: str, source: str, note: str) -> dict:
    return {"value": round(float(value), 4), "unit": unit, "source": source, "note": note}
