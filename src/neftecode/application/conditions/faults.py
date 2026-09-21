import copy

from neftecode.application.contracts import MEASURED_ORIGIN

from .changes import ConditionsError

SOURCE_FAULTS = {
    "healthy": {},
    "frozen_pak": {"pak_frozen": True, "pak_usable": False},
    "stale_lab": {"lab_age_hours": 120.0, "lab_usable": False},
    "both_broken": {"lab_value": None, "lab_usable": False, "pak_frozen": True, "pak_usable": False},
    "missing_telemetry": {"telemetry_missing_fraction": 0.9},
}


def healthy_state() -> dict:
    return {"decision_time": "2026-01-05T08:00:00",
            "lab_value": 8.0, "lab_age_hours": 5.0, "lab_usable": True,
            "pak_value": 8.4, "pak_age_minutes": 10.0, "pak_usable": True,
            "pak_frozen": False, "pak_conflict": False, "telemetry_missing_fraction": 0.0,
            "origin": "synthetic_scenario_state"}


def apply_source_failure(state: dict, fault: str) -> dict:
    if fault not in SOURCE_FAULTS:
        raise ConditionsError(f"Неизвестный отказ источника «{fault}». "
                              f"Доступно: {', '.join(sorted(SOURCE_FAULTS))}")
    out = {**state, **SOURCE_FAULTS[fault]}
    if fault != "healthy":
        if out.get("origin") != MEASURED_ORIGIN:
            out["origin"] = "injected_source_failure"
        out["injected_fault"] = fault
        out["injection"] = f"Модельная инъекция отказа: {fault}. Это не наблюдение из данных."
    return out


def state_under(snapshot: dict | None, fault: str) -> dict:
    """Состояние источников на момент решения: реальный срез или синтетика, поверх — инъекция отказа."""
    base = copy.deepcopy(snapshot["state"]) if snapshot is not None else healthy_state()
    return apply_source_failure(base, fault)
