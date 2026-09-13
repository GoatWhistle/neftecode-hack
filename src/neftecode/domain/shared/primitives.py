"""Общие примитивы и статусы доменного слоя."""
import math
from datetime import datetime

SOURCES = ("given", "derived", "scenario", "open")
QUALITIES = ("sulfur_mgkg", "t95_c", "cetane_number")
QUALITY_DIRECTION = {"sulfur_mgkg": "max", "t95_c": "max", "cetane_number": "min"}
PASS, FAIL, UNKNOWN = "pass", "fail", "unknown"
CHECK_STATUSES = (PASS, FAIL, UNKNOWN)
PROPOSED, CONFIRMED, REJECTED, EXPIRED = "proposed", "confirmed", "rejected", "expired"
EXECUTION_STATUSES = (PROPOSED, CONFIRMED, REJECTED, EXPIRED)
HOLD, RECOMMEND_SCENARIO, REFUSE = "hold", "recommend_scenario", "refuse"
DECISION_STATUSES = (HOLD, RECOMMEND_SCENARIO, REFUSE)
SCENARIO_SCOPE, CONFIRMED_SCOPE = "synthetic_scenario", "confirmed_model"

class ContractError(ValueError):
    """Нарушение доменного контракта."""

def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)

def _clean_number(value, where):
    if value is None: return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ContractError(f"{where}: ожидается число или None, получено {type(value).__name__}")
    return float(value) if math.isfinite(value) else None

def _time(value, where, required=True):
    if value is None:
        if required: raise ContractError(f"{where}: время обязательно")
        return None
    if isinstance(value, datetime): return value.isoformat()
    text=str(value)
    try: datetime.fromisoformat(text)
    except ValueError as exc: raise ContractError(f"{where}: время «{text}» не в формате ISO 8601") from exc
    return text
