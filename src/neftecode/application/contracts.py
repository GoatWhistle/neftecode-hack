"""Typed messages exchanged by application use cases and their adapters."""
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence, TypeAlias

from neftecode.domain.production.state import TankState

DecisionResult: TypeAlias = dict[str, object]
PlanningResult: TypeAlias = dict[str, object]
ReplayResult: TypeAlias = dict[str, object]


def _mapping(raw: Mapping[str, Any], key: str) -> dict[str, object]:
    value = raw.get(key)
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"{key} должен быть JSON-объектом")
    return dict(value)


def _optional_float(value: object, key: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} должен быть числом или null")
    return float(value)


@dataclass(frozen=True)
class LiveForecast:
    """Forecast crossing the live application boundary."""
    model: str | None
    value: float | None
    lower: float | None
    upper: float | None
    available: bool
    reason: str = ""
    #: Заявленное покрытие интервала и фактическое на тесте 2026 (из metrics.json), если известны.
    coverage_target: float | None = None
    coverage_test: float | None = None

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "LiveForecast":
        model = raw.get("model")
        if model is not None and not isinstance(model, str):
            raise ValueError("model должен быть строкой или null")
        reason = raw.get("reason", "")
        if not isinstance(reason, str):
            raise ValueError("reason должен быть строкой")
        return cls(
            model=model,
            value=_optional_float(raw.get("value"), "value"),
            lower=_optional_float(raw.get("lower"), "lower"),
            upper=_optional_float(raw.get("upper"), "upper"),
            available=raw.get("available") is True,
            reason=reason,
            coverage_target=_optional_float(raw.get("coverage_target"), "coverage_target"),
            coverage_test=_optional_float(raw.get("coverage_test", raw.get("coverage_test_2026")), "coverage_test"),
        )

    def to_dict(self) -> dict[str, object]:
        out = {"model": self.model, "value": self.value, "lower": self.lower,
               "upper": self.upper, "available": self.available, "reason": self.reason}
        if self.coverage_target is not None:
            out["coverage_target"] = self.coverage_target
        if self.coverage_test is not None:
            out["coverage_test"] = self.coverage_test
        return out


@dataclass(frozen=True)
class LiveSnapshot:
    at: str
    state: Mapping[str, object]
    trust: Mapping[str, object]
    features: Mapping[str, object] = field(default_factory=dict)
    snapshot_id: str | None = None
    trust_cfg: Mapping[str, object] | None = None
    source_period: Mapping[str, object] | None = None
    feature_schema: Sequence[Mapping[str, object]] = ()
    feature_schema_hash: str | None = None
    schema_version: str = "v1"
    #: Откуда пороги доверия: derived:model.pkl, derived:artifacts/source_rules.json или fallback:config/experiment.json.
    trust_origin: str | None = None

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "LiveSnapshot":
        at = raw.get("at")
        if not isinstance(at, str) or not at.strip():
            raise ValueError("Snapshot не содержит нормализованное время at")
        feature_schema = raw.get("feature_schema") or ()
        if not isinstance(feature_schema, Sequence) or isinstance(feature_schema, (str, bytes)):
            raise ValueError("feature_schema должен быть списком")
        trust_origin = raw.get("trust_origin")
        if trust_origin is not None and not isinstance(trust_origin, str):
            raise ValueError("trust_origin должен быть строкой или null")
        return cls(
            at=at,
            state=_mapping(raw, "state"),
            trust=_mapping(raw, "trust"),
            features=_mapping(raw, "features"),
            snapshot_id=raw.get("snapshot_id"),
            trust_cfg=_mapping(raw, "trust_config"),
            source_period=_mapping(raw, "source_period"),
            feature_schema=tuple(feature_schema),
            feature_schema_hash=raw.get("feature_schema_hash"),
            schema_version=str(raw.get("schema_version", "v1")),
            trust_origin=trust_origin,
        )

    def to_dict(self) -> dict[str, object]:
        return {"at": self.at, "state": dict(self.state), "trust": dict(self.trust),
                "features": dict(self.features or {}), "snapshot_id": self.snapshot_id,
                "trust_config": dict(self.trust_cfg or {}), "source_period": dict(self.source_period or {}),
                "feature_schema": list(self.feature_schema), "feature_schema_hash": self.feature_schema_hash,
                "schema_version": self.schema_version, "trust_origin": self.trust_origin}


@dataclass(frozen=True)
class LiveAdviceResult:
    at: str
    scenario_id: str
    state: Mapping[str, object]
    trust: Mapping[str, object]
    forecast: LiveForecast
    decision: Mapping[str, object] | None
    explanation: Mapping[str, object] | None
    bound_sulfur_mgkg: float | None = None
    error: str | None = None
    note: str = ""
    error_kind: str | None = None
    inventories: Mapping[str, float] = field(default_factory=dict)
    bound_inflow_sulfur_mgkg: float | None = None
    #: Что и откуда попало в связанный сценарий: уставки, отклик, приток, окно резервуара.
    binding: Mapping[str, object] | None = None

    def to_dict(self) -> dict[str, object]:
        result = {"at": self.at, "scenario_id": self.scenario_id, "state": dict(self.state),
                  "trust": dict(self.trust), "forecast": self.forecast.to_dict(),
                  "decision": self.decision, "explanation": self.explanation,
                  "note": self.note}
        if self.bound_sulfur_mgkg is not None:
            result["bound_sulfur_mgkg"] = self.bound_sulfur_mgkg
        if self.bound_inflow_sulfur_mgkg is not None:
            result["bound_inflow_sulfur_mgkg"] = self.bound_inflow_sulfur_mgkg
        if self.binding is not None:
            result["binding"] = dict(self.binding)
        if self.error is not None:
            result["error"] = self.error
        return result


@dataclass(frozen=True)
class DataRejection:
    reason: str
    missing: Sequence[str] = ()


@dataclass(frozen=True)
class DecisionCommand:
    state: Mapping[str, object] | None = None
    confirmed: Sequence[tuple[float, Mapping[str, float]]] = ()
    budget: int = 600
    trust_cfg: Mapping[str, object] | None = None
    raw_scenario: Mapping[str, object] | None = None
    initial_tanks: Mapping[str, TankState] | None = None
    current_operation: Mapping[str, object] | None = None
    data_rejection: DataRejection | None = None


@dataclass(frozen=True)
class PlanningCommand:
    confirmed: Sequence[tuple[float, Mapping[str, float]]] = ()
    budget: int = 120


@dataclass(frozen=True)
class ReplayCommand:
    moments: Sequence[Mapping[str, object]] = ()
    mode: str = "simulated"
    execution: object | None = None


@dataclass(frozen=True)
class LiveAdviceCommand:
    at: str
    scenario_id: str
    budget: int = 400
