"""Executable chain scenario: what is measured, what is assumed and what stays unknown.

Every physical number carries a unit and a provenance, so a scenario constant can never be
read back as if it were a plant measurement. Loading validates structure, units and ranges;
a missing optional quality is preserved as unknown instead of silently becoming a pass.
"""
from dataclasses import dataclass, field
import math

from neftecode.domain.shared.primitives import PRODUCT_LIMITS, QUALITIES, SOURCES

SCHEMA = "neftecode.scenario.v1"

#: Provenance of a scenario number. See config/parameters.json for the same vocabulary.

#: Units accepted for each named quantity. A scenario declaring another unit is rejected
#: rather than converted by guesswork.
UNITS = {
    "sulfur_mgkg": "мг/кг",
    "t95_c": "°C",
    "cetane_number": "ед.",
    "density_kgm3": "кг/м3",
    "mass_t": "т",
    "flow_tph": "т/ч",
    "temperature_c": "°C",
    "pressure_mpa": "МПа",
    "volume_flow_m3h": "м3/ч",
    "sulfur_wt_pct": "% масс.",
    "fraction": "доля",
    "cost_per_t": "усл.ед./т",
    "hours": "ч",
}

#: Quality properties a blended product is judged on. Expert message 517 requires all three.

#: Which way a limit constrains the property.


class ScenarioError(ValueError):
    """Raised with a message naming the field, so a broken scenario is fixable without reading code."""


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


@dataclass(frozen=True)
class Quantity:
    """A number that always remembers its unit and where it came from."""

    value: float
    unit: str
    source: str
    note: str | None = None

    def to_dict(self) -> dict:
        return {"value": self.value, "unit": self.unit, "source": self.source, "note": self.note}

    @property
    def measured(self) -> bool:
        """True only for values traceable to the issued data, never for our own assumptions."""
        return self.source in ("given", "derived", "measured")


def quantity(raw, kind: str, where: str, *, allow_negative: bool = False) -> Quantity:
    if not isinstance(raw, dict):
        raise ScenarioError(f"{where}: ожидается объект со значением, единицей и источником, получено {type(raw).__name__}")
    missing = [k for k in ("value", "unit", "source") if k not in raw]
    if missing:
        raise ScenarioError(f"{where}: не заданы обязательные поля {', '.join(missing)}")
    value = raw["value"]
    if not _finite(value):
        raise ScenarioError(f"{where}: значение должно быть конечным числом, получено {value!r}")
    if value < 0 and not allow_negative:
        raise ScenarioError(f"{where}: отрицательное значение {value} недопустимо для этой величины")
    expected = UNITS.get(kind)
    if expected is None:
        raise ScenarioError(f"{where}: неизвестный вид величины {kind}")
    if raw["unit"] != expected:
        raise ScenarioError(f"{where}: единица «{raw['unit']}» не совпадает с ожидаемой «{expected}»; "
                            f"пересчёт по догадке запрещён")
    if raw["source"] not in SOURCES:
        raise ScenarioError(f"{where}: источник «{raw['source']}» не из набора {', '.join(SOURCES)}")
    return Quantity(float(value), raw["unit"], raw["source"], raw.get("note"))


def optional_quantity(raw, kind: str, where: str) -> Quantity | None:
    """An absent optional quality stays None and later blocks the plan as unknown."""
    return None if raw is None else quantity(raw, kind, where)


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
    """A blending component with a finite inventory and its own declared properties."""

    tank_id: str
    name: str
    available: bool
    inventory: Quantity
    max_outflow: Quantity
    inflow: Quantity
    cost_per_t: Quantity
    properties: dict[str, Quantity | None]
    note: str | None = None
    #: True when this component leaves the modelled chain, so its sulfur is whatever the chain
    #: produces at the current regime rather than a standing scenario constant. A real forecast
    #: bound into the scenario overrides it: a measurement outranks a model.
    sulfur_from_chain: bool = False
    #: Sulfur of the stream entering this tank, when a measurement-based forecast supplies it.
    #: The tank's own property stays the sulfur of what is already stored.
    inflow_sulfur: Quantity | None = None

    def property_value(self, name: str) -> float | None:
        q = self.properties.get(name)
        return None if q is None else q.value

    def to_dict(self) -> dict:
        return {"tank_id": self.tank_id, "name": self.name, "available": self.available,
                "inventory": self.inventory.to_dict(), "max_outflow": self.max_outflow.to_dict(),
                "inflow": self.inflow.to_dict(), "cost_per_t": self.cost_per_t.to_dict(),
                "properties": {k: (v.to_dict() if v else None) for k, v in self.properties.items()},
                "note": self.note, "sulfur_from_chain": self.sulfur_from_chain,
                "inflow_sulfur_mgkg": self.inflow_sulfur.to_dict() if self.inflow_sulfur else None}


@dataclass(frozen=True)
class ProductSpec:
    """Declared product limits. A None limit is unknown, which is not the same as no limit."""

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
    """Cetane additive. Its dose response is our assumption, not a supplied curve."""

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


#: How a proposed control change reaches the plant. Experts said (Q&A 11.09) that both units run
#: feedback control systems that react quickly, so the operator changes a setpoint and the loop moves
#: the equipment. The response of product quality is still the stage's declared lag.
FEEDBACK_SETPOINT = "feedback_setpoint"
ACTUATION_KINDS = (FEEDBACK_SETPOINT,)


@dataclass(frozen=True)
class ControlActuation:
    """Who executes a control change and what is known about the loop."""

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
    """Controls of one process stage with their declared ranges and response lag."""

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
    """The blend and throughput running right now. Without it, "keep the regime" is undefined."""

    recipe: dict[str, float]
    throughput: Quantity

    def to_dict(self) -> dict:
        return {"recipe": dict(self.recipe), "throughput": self.throughput.to_dict()}


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

    def tank(self, tank_id: str) -> Tank:
        for t in self.tanks:
            if t.tank_id == tank_id:
                return t
        raise ScenarioError(f"Резервуар {tank_id} не описан в сценарии")

    def available_tanks(self) -> tuple[Tank, ...]:
        return tuple(t for t in self.tanks if t.available)

    def unknown_properties(self) -> dict[str, list[str]]:
        """Qualities a tank does not declare. These make the blend result unknown, not compliant."""
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
        }
