from copy import deepcopy
from dataclasses import dataclass
from typing import Protocol

from neftecode.application.conditions import SOURCE_FAULTS, apply_changes, state_under
from .catalog import snapshot_id
from .time import HistoryError, local_moment


class HistorySource(Protocol):
    def get_snapshot(self, key: str) -> dict: ...
    def prepare_at(self, at: str) -> tuple[dict, dict]: ...
    def provenance(self) -> dict: ...


@dataclass(frozen=True)
class HistoryRequest:
    at: str | None = None
    snapshot: str | None = None
    fault: str = "healthy"
    changes: tuple[dict, ...] = ()


@dataclass
class PrepareHistoricalState:
    source: HistorySource

    def execute(self, request: HistoryRequest) -> dict:
        if not isinstance(request, HistoryRequest):
            raise TypeError("Нужен HistoryRequest")
        if (request.at is None) == (request.snapshot is None):
            raise HistoryError("ambiguous_moment", "Укажите ровно одно: at или snapshot")
        if not isinstance(request.fault, str) or request.fault not in SOURCE_FAULTS:
            raise HistoryError("unknown_fault", "Неизвестный внесённый отказ источника")
        details = {}
        if request.at is not None:
            requested = local_moment(request.at).isoformat()
            snapshot, details = self.source.prepare_at(requested)
        else:
            snapshot = self.source.get_snapshot(request.snapshot)
            requested = snapshot["at"]
        if local_moment(snapshot["at"]) != local_moment(requested):
            raise HistoryError("moment_mismatch", "Подготовленное состояние не совпадает с выбранным моментом")
        if snapshot["state"].get("decision_time") != snapshot["at"]:
            raise HistoryError("state_time_mismatch", "Время измерений не совпадает со временем среза")
        provenance = self.source.provenance() if request.at is not None else {
            key: snapshot.get(key) for key in ("model_fingerprint", "source_rules_fingerprint")}
        return {
            "available": True, "reason": None, "requested_at": request.at or requested,
            "effective_at": snapshot["at"], "timezone": "source-local", "alignment": "exact_as_of",
            "grid_minutes": 10, "snapshot": deepcopy(snapshot),
            "conditions": {"at": request.at, "snapshot": request.snapshot, "fault": request.fault,
                           "changes": deepcopy(list(request.changes))},
            "provenance": provenance, **details,
            "note": "Исторические условия; последствия неисполненных действий здесь не наблюдаются.",
        }


def run_prepared_history(prepared: dict, raw: dict, runner, budget: int, trust_cfg: dict,
                         trust_origin=None, response_model=None) -> dict:
    if prepared.get("available") is not True:
        raise HistoryError("history_unavailable", prepared.get("reason") or "Момент недоступен")
    chosen = deepcopy(prepared["snapshot"])
    conditions = prepared["conditions"]
    changed = apply_changes(raw, conditions["changes"])
    state = state_under(chosen, conditions["fault"])
    result = runner(changed, state, budget, trust_cfg, trust_origin=trust_origin,
                    snapshot=chosen, response_model=response_model)
    meta = {key: value for key, value in prepared.items() if key != "snapshot"}
    return {**result, "history": meta, "applied": deepcopy(conditions["changes"]),
            "fault": conditions["fault"], "snapshot": snapshot_id(chosen),
            "state_origin": state.get("origin"), "injection": state.get("injection")}
