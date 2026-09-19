from dataclasses import dataclass, field
from datetime import datetime

from neftecode.domain.shared.primitives import ContractError, SOURCES, SCENARIO_SCOPE, _clean_number, _time

from neftecode.domain.production.state import TankState
from neftecode.domain.shared.actions import PendingAction

@dataclass(frozen=True)
class Observation:

    tag_id: str
    source: str
    value: float | None
    unit: str
    measured_at: str
    available_at: str
    validity: str = "ok"
    issues: tuple[str, ...] = ()
    provenance: str = "given"

    VALIDITY = ("ok", "suspect", "unusable")

    def __post_init__(self):
        if not self.tag_id:
            raise ContractError("Observation.tag_id: обязательно")
        object.__setattr__(self, "value", _clean_number(self.value, f"Observation[{self.tag_id}].value"))
        object.__setattr__(self, "measured_at", _time(self.measured_at, f"Observation[{self.tag_id}].measured_at"))
        object.__setattr__(self, "available_at", _time(self.available_at, f"Observation[{self.tag_id}].available_at"))
        if self.available_at < self.measured_at:
            raise ContractError(f"Observation[{self.tag_id}]: результат не может быть доступен раньше измерения")
        if self.validity not in self.VALIDITY:
            raise ContractError(f"Observation[{self.tag_id}].validity: ожидается одно из {self.VALIDITY}")
        if self.provenance not in SOURCES:
            raise ContractError(f"Observation[{self.tag_id}].provenance: ожидается одно из {SOURCES}")

    @property
    def usable(self) -> bool:
        return self.validity == "ok" and self.value is not None

    def visible_at(self, when: str | datetime) -> bool:
        return self.available_at <= _time(when, "visible_at")

    def age_hours(self, when: str | datetime) -> float:
        return (datetime.fromisoformat(_time(when, "age_hours"))
                - datetime.fromisoformat(self.measured_at)).total_seconds() / 3600

    def to_dict(self) -> dict:
        return {"tag_id": self.tag_id, "source": self.source, "value": self.value, "unit": self.unit,
                "measured_at": self.measured_at, "available_at": self.available_at,
                "validity": self.validity, "issues": list(self.issues), "provenance": self.provenance}

    @classmethod
    def from_dict(cls, raw: dict) -> "Observation":
        return cls(raw["tag_id"], raw["source"], raw.get("value"), raw["unit"], raw["measured_at"],
                   raw["available_at"], raw.get("validity", "ok"), tuple(raw.get("issues", ())),
                   raw.get("provenance", "given"))
@dataclass(frozen=True)
class PlantState:

    as_of: str
    observations: tuple[Observation, ...] = ()
    features: dict[str, float | None] = field(default_factory=dict)
    tanks: tuple[TankState, ...] = ()
    pending_actions: tuple[PendingAction, ...] = ()
    current_controls: dict[str, float] = field(default_factory=dict)
    current_recipe: dict[str, float] = field(default_factory=dict)
    current_throughput_tph: float | None = None
    data_quality: dict = field(default_factory=dict)
    missing_inputs: tuple[str, ...] = ()
    operating_region: str = "unknown"
    origin: str = SCENARIO_SCOPE

    def __post_init__(self):
        object.__setattr__(self, "as_of", _time(self.as_of, "PlantState.as_of"))
        late = [o.tag_id for o in self.observations if not o.visible_at(self.as_of)]
        if late:
            raise ContractError(f"PlantState: наблюдения {', '.join(late)} ещё не были доступны на {self.as_of}; "
                                f"это утечка из будущего")
        if self.current_recipe:
            total = sum(self.current_recipe.values())
            if abs(total - 1.0) > 1e-6:
                raise ContractError(f"PlantState.current_recipe: доли дают {total:.6f}, требуется 1.0")
        object.__setattr__(self, "current_throughput_tph",
                           _clean_number(self.current_throughput_tph, "PlantState.current_throughput_tph"))

    def tank(self, tank_id: str) -> TankState:
        for t in self.tanks:
            if t.tank_id == tank_id:
                return t
        raise ContractError(f"PlantState: резервуар {tank_id} отсутствует в состоянии")

    def confirmed_actions(self) -> tuple[PendingAction, ...]:
        return tuple(a for a in self.pending_actions if a.executed)

    def to_dict(self) -> dict:
        return {"as_of": self.as_of, "observations": [o.to_dict() for o in self.observations],
                "features": dict(self.features), "tanks": [t.to_dict() for t in self.tanks],
                "pending_actions": [a.to_dict() for a in self.pending_actions],
                "current_controls": dict(self.current_controls), "current_recipe": dict(self.current_recipe),
                "current_throughput_tph": self.current_throughput_tph, "data_quality": dict(self.data_quality),
                "missing_inputs": list(self.missing_inputs), "operating_region": self.operating_region,
                "origin": self.origin}

    @classmethod
    def from_dict(cls, raw: dict) -> "PlantState":
        return cls(raw["as_of"],
                   tuple(Observation.from_dict(o) for o in raw.get("observations", ())),
                   dict(raw.get("features", {})),
                   tuple(TankState.from_dict(t) for t in raw.get("tanks", ())),
                   tuple(PendingAction.from_dict(a) for a in raw.get("pending_actions", ())),
                   dict(raw.get("current_controls", {})), dict(raw.get("current_recipe", {})),
                   raw.get("current_throughput_tph"), dict(raw.get("data_quality", {})),
                   tuple(raw.get("missing_inputs", ())), raw.get("operating_region", "unknown"),
                   raw.get("origin", SCENARIO_SCOPE))
@dataclass(frozen=True)
class ForecastValue:

    target: str
    horizon_hours: float
    value: float | None
    lower: float | None
    upper: float | None
    model_version: str
    calibration_version: str | None = None
    valid_from: str | None = None
    applicability: str = "unknown"
    limitations: tuple[str, ...] = ()

    def __post_init__(self):
        for name in ("value", "lower", "upper"):
            object.__setattr__(self, name, _clean_number(getattr(self, name), f"ForecastValue.{name}"))
        object.__setattr__(self, "valid_from", _time(self.valid_from, "ForecastValue.valid_from", required=False))
        if self.available and not self.lower <= self.value <= self.upper:
            raise ContractError(f"ForecastValue[{self.target}]: границы {self.lower}…{self.upper} не окружают "
                                f"точечный прогноз {self.value}")

    @property
    def available(self) -> bool:
        return None not in (self.value, self.lower, self.upper)

    def usable_at(self, when) -> bool:
        return self.valid_from is None or self.valid_from <= _time(when, "ForecastValue.usable_at")

    def to_dict(self) -> dict:
        return {"target": self.target, "horizon_hours": self.horizon_hours, "value": self.value,
                "lower": self.lower, "upper": self.upper, "model_version": self.model_version,
                "calibration_version": self.calibration_version, "valid_from": self.valid_from,
                "applicability": self.applicability, "limitations": list(self.limitations)}

    @classmethod
    def from_dict(cls, raw: dict) -> "ForecastValue":
        return cls(raw["target"], raw["horizon_hours"], raw.get("value"), raw.get("lower"), raw.get("upper"),
                   raw["model_version"], raw.get("calibration_version"), raw.get("valid_from"),
                   raw.get("applicability", "unknown"), tuple(raw.get("limitations", ())))
