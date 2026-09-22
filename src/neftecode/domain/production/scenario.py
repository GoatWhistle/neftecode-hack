from dataclasses import dataclass, field

from neftecode.domain.shared.primitives import PRODUCT_LIMITS, QUALITIES, SOURCES

from .quantities import (Quantity, SCHEMA, ScenarioError, UNITS, _finite, optional_quantity, quantity)

__all__ = ["ACTUATION_KINDS", "Additive", "ControlActuation", "CurrentOperation", "FEEDBACK_SETPOINT",
           "Horizon", "ProductSpec", "Quantity", "SCHEMA", "Scenario", "ScenarioError", "Stage", "Tank",
           "TankParkConfig",
           "UNITS", "_finite", "optional_quantity", "quantity"]


@dataclass(frozen=True)
class Horizon:
    hours: float
    step_minutes: int

    @property
    def steps(self) -> int:
        return int(round(self.hours * 60 / self.step_minutes))

    def times_hours(self) -> list[float]:
        return [i * self.step_minutes / 60 for i in range(self.steps + 1)]


@dataclass(frozen=True)
class Tank:

    tank_id: str
    name: str
    available: bool
    inventory: Quantity
    max_outflow: Quantity
    inflow: Quantity
    cost_per_t: Quantity
    properties: dict[str, Quantity | None]
    note: str | None = None
    sulfur_from_chain: bool = False
    inflow_sulfur: Quantity | None = None
    on_demand: bool = False
    production_lead_time_hours: float = 0.0
    production_rate_tph: float = 0.0

    def property_value(self, name: str) -> float | None:
        q = self.properties.get(name)
        return None if q is None else q.value

    def to_dict(self) -> dict:
        return {"tank_id": self.tank_id, "name": self.name, "available": self.available,
                "inventory": self.inventory.to_dict(), "max_outflow": self.max_outflow.to_dict(),
                "inflow": self.inflow.to_dict(), "cost_per_t": self.cost_per_t.to_dict(),
                "properties": {k: (v.to_dict() if v else None) for k, v in self.properties.items()},
                "note": self.note, "sulfur_from_chain": self.sulfur_from_chain,
                "inflow_sulfur_mgkg": self.inflow_sulfur.to_dict() if self.inflow_sulfur else None,
                "on_demand": self.on_demand,
                "production_lead_time_hours": self.production_lead_time_hours,
                "production_rate_tph": self.production_rate_tph}


@dataclass(frozen=True)
class ProductSpec:

    limits: dict[str, Quantity | None]

    def limit_value(self, name: str) -> float | None:
        q = self.limits.get(name)
        return None if q is None else q.value

    def unknown_limits(self) -> list[str]:
        return [name for name in PRODUCT_LIMITS if self.limits.get(name) is None]

    def to_dict(self) -> dict:
        return {k: (v.to_dict() if v else None) for k, v in self.limits.items()}


@dataclass(frozen=True)
class Additive:

    max_dose_fraction: Quantity
    price_per_t: Quantity
    cetane_gain_per_dose_pct: Quantity | None
    affects: tuple[str, ...]

    def to_dict(self) -> dict:
        return {"max_dose_fraction": self.max_dose_fraction.to_dict(),
                "price_per_t": self.price_per_t.to_dict(),
                "cetane_gain_per_dose_pct": (self.cetane_gain_per_dose_pct.to_dict()
                                             if self.cetane_gain_per_dose_pct else None),
                "affects": list(self.affects)}


FEEDBACK_SETPOINT = "feedback_setpoint"
ACTUATION_KINDS = (FEEDBACK_SETPOINT,)


@dataclass(frozen=True)
class ControlActuation:

    kind: str
    loop: str
    measured_tag: str | None
    source: str
    note: str = ""

    def __post_init__(self):
        if self.kind not in ACTUATION_KINDS:
            raise ScenarioError(f"actuation.kind: неизвестный способ исполнения {self.kind!r}")
        if not isinstance(self.loop, str) or not self.loop.strip():
            raise ScenarioError("actuation.loop: нужно описать контур регулирования или его отсутствие на схеме")
        if self.measured_tag is not None and (not isinstance(self.measured_tag, str) or not self.measured_tag.strip()):
            raise ScenarioError("actuation.measured_tag: тег должен быть строкой или null")
        if self.source not in SOURCES:
            raise ScenarioError(f"actuation.source: неизвестное происхождение {self.source!r}")

    @property
    def instruction(self) -> str:
        return "изменить уставку регулятора"

    def to_dict(self) -> dict:
        return {"kind": self.kind, "loop": self.loop, "measured_tag": self.measured_tag,
                "source": self.source, "note": self.note}


@dataclass(frozen=True)
class Stage:

    stage_id: str
    controls: dict[str, dict]
    response_lag_hours: Quantity
    model: dict

    def control_range(self, name: str) -> tuple[float, float]:
        spec = self.controls[name]
        return spec["min"].value, spec["max"].value

    def to_dict(self) -> dict:
        return {"stage_id": self.stage_id, "response_lag_hours": self.response_lag_hours.to_dict(),
                "controls": {name: {k: (v.to_dict() if isinstance(v, (Quantity, ControlActuation)) else v)
                                    for k, v in spec.items()} for name, spec in self.controls.items()},
                "model": self.model}


@dataclass(frozen=True)
class CurrentOperation:

    recipe: dict[str, float]
    throughput: Quantity

    def to_dict(self) -> dict:
        return {"recipe": dict(self.recipe), "throughput": self.throughput.to_dict()}


@dataclass(frozen=True)
class TankParkConfig:
    component_tank_id: str
    tank_count: int
    capacity_m3: float
    density_kgm3: float
    passport_duration_h: float
    nominal_drain_h: float
    phase_offsets_h: tuple[float, ...]
    source: str = "scenario"
    schema: str = "tank-park-scenario/1"

    def to_dict(self) -> dict:
        return {"schema": self.schema, "component_tank_id": self.component_tank_id,
                "tank_count": self.tank_count, "capacity_m3": self.capacity_m3,
                "density_kgm3": self.density_kgm3, "passport_duration_h": self.passport_duration_h,
                "nominal_drain_h": self.nominal_drain_h, "phase_offsets_h": list(self.phase_offsets_h),
                "source": self.source}


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    title: str
    description: str
    kind: str
    horizon: Horizon
    crude: dict[str, Quantity]
    stages: dict[str, Stage]
    product: ProductSpec
    tanks: tuple[Tank, ...]
    current_operation: CurrentOperation
    additive: Additive | None
    economics: dict[str, Quantity]
    policy: dict
    assumptions: tuple[str, ...]
    expected: dict = field(default_factory=dict)
    tank_park: TankParkConfig | None = None

    def tank(self, tank_id: str) -> Tank:
        for t in self.tanks:
            if t.tank_id == tank_id:
                return t
        raise ScenarioError(f"Резервуар {tank_id} не описан в сценарии")

    def available_tanks(self) -> tuple[Tank, ...]:
        return tuple(t for t in self.tanks if t.available)

    def unknown_properties(self) -> dict[str, list[str]]:
        return {t.tank_id: [q for q in QUALITIES if t.properties.get(q) is None] for t in self.tanks}

    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA, "id": self.scenario_id, "title": self.title,
            "description": self.description, "kind": self.kind,
            "horizon": {"hours": self.horizon.hours, "step_minutes": self.horizon.step_minutes},
            "crude": {k: v.to_dict() for k, v in self.crude.items()},
            "stages": {k: v.to_dict() for k, v in self.stages.items()},
            "product": self.product.to_dict(),
            "tanks": [t.to_dict() for t in self.tanks],
            "current_operation": self.current_operation.to_dict(),
            "additive": self.additive.to_dict() if self.additive else None,
            "economics": {k: v.to_dict() for k, v in self.economics.items()},
            "policy": self.policy,
            "assumptions": list(self.assumptions),
            "expected": self.expected,
            "tank_park": self.tank_park.to_dict() if self.tank_park else None,
        }
