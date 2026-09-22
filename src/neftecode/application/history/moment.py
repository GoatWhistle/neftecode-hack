"""Общие правила момента истории для serve и stack: покрытие, доступность модели, сборка среза."""

from copy import deepcopy

from .time import HistoryError, local_moment

SNAPSHOT_SCHEMA = "v1"


def check_moment(at: str, coverage: dict):
    """Момент внутри поставленной телеметрии и не раньше доступности калибровки модели."""
    when = local_moment(at)
    if when < local_moment(coverage["start"]) or when > local_moment(coverage["end"]):
        raise HistoryError("outside_coverage", "Момент вне поставленного периода телеметрии")
    valid = coverage["model_valid_from"]
    valid = local_moment(valid + "T00:00:00" if len(valid) == 10 else valid)
    if when < valid:
        raise HistoryError("model_not_available", "На этот момент модель и калибровка ещё не были доступны")
    return when


def assemble_snapshot(data_snapshot: dict, forecast: dict, forecast_no_pak: dict,
                      model_fingerprint: str | None) -> dict:
    """Срез того же вида, что build_snapshot, из причинного состояния data-service и двух ветвей
    прогноза model-service на одном snapshot_id. Решение по нему считает обычный decision-service."""
    strip = lambda item: {k: v for k, v in item.items() if k != "at"}
    state = deepcopy(data_snapshot["state"])
    return {"schema_version": SNAPSHOT_SCHEMA, "at": data_snapshot["at"], "label": "", "why": "",
            "state": state, "trust": deepcopy(data_snapshot["trust"]),
            "forecast": strip(forecast), "forecast_no_pak": strip(forecast_no_pak),
            "measured": dict(state.get("measurements") or {}), "synthetic_edits": [],
            "model_fingerprint": model_fingerprint, "source_rules_fingerprint": None}
