from dataclasses import dataclass, replace

from neftecode.domain.shared.primitives import (ContractError, QUALITIES, _finite, _clean_number, _time,
                                                volume_additive_density)

@dataclass(frozen=True)
class TankState:

    tank_id: str
    available: bool
    inventory_t: float
    properties: dict[str, float | None]
    inflow_tph: float = 0.0
    max_outflow_tph: float = 0.0
    observed_at: str | None = None
    provenance: str = "scenario"
    on_demand: bool = False
    produced_t: float = 0.0
    production_lead_time_hours: float = 0.0
    production_rate_tph: float = 0.0
    elapsed_hours: float = 0.0

    def __post_init__(self):
        if not _finite(self.inventory_t) or self.inventory_t < 0:
            raise ContractError(f"TankState[{self.tank_id}].inventory_t: остаток должен быть конечным и неотрицательным")
        cleaned = {name: _clean_number(self.properties.get(name), f"TankState[{self.tank_id}].{name}")
                   for name in QUALITIES}
        object.__setattr__(self, "properties", cleaned)
        object.__setattr__(self, "observed_at", _time(self.observed_at, "TankState.observed_at", required=False))

    def unknown_properties(self) -> list[str]:
        return [name for name in QUALITIES if self.properties[name] is None]

    def makeable_by(self, hours: float) -> float:
        if not self.on_demand:
            return float("inf")
        running = max(0.0, hours - self.production_lead_time_hours)
        return self.production_rate_tph * running

    def advance(self, hours: float) -> "TankState":
        if not _finite(hours) or hours < 0:
            raise ContractError(f"TankState[{self.tank_id}].advance: длительность должна быть конечной и неотрицательной")
        return replace(self, elapsed_hours=self.elapsed_hours + hours)

    def draw(self, mass_t: float) -> "TankState":
        if not _finite(mass_t) or mass_t < 0:
            raise ContractError(f"TankState[{self.tank_id}].draw: масса отбора должна быть конечной и неотрицательной")
        if self.on_demand:
            return replace(self, produced_t=self.produced_t + mass_t)
        if mass_t > self.inventory_t + 1e-9:
            raise ContractError(f"TankState[{self.tank_id}]: отбор {mass_t:.3f} т превышает остаток {self.inventory_t:.3f} т")
        return replace(self, inventory_t=max(0.0, self.inventory_t - mass_t))

    def add(self, mass_t: float) -> "TankState":
        if not _finite(mass_t) or mass_t < 0:
            raise ContractError(f"TankState[{self.tank_id}].add: масса притока должна быть конечной и неотрицательной")
        return replace(self, inventory_t=self.inventory_t + mass_t)

    def mix_in(self, mass_t: float, properties: dict[str, float | None]) -> "TankState":
        if not _finite(mass_t) or mass_t < 0:
            raise ContractError(f"TankState[{self.tank_id}].mix_in: масса должна быть конечной и неотрицательной")
        if mass_t == 0:
            return self
        total = self.inventory_t + mass_t
        merged = dict(self.properties)
        if total > 0:
            for name in QUALITIES:
                incoming = properties.get(name)
                current = self.properties.get(name)
                if incoming is None or not _finite(incoming):
                    merged[name] = None
                elif self.inventory_t <= 1e-12:
                    merged[name] = incoming
                elif current is None:
                    merged[name] = None
                elif name == "density_kgm3":
                    merged[name] = volume_additive_density({"stock": self.inventory_t, "inflow": mass_t},
                                                           {"stock": current, "inflow": incoming})
                else:
                    merged[name] = (self.inventory_t * current + mass_t * incoming) / total
        return replace(self, inventory_t=total, properties=merged)

    def to_dict(self) -> dict:
        return {"tank_id": self.tank_id, "available": self.available, "inventory_t": self.inventory_t,
                "properties": dict(self.properties), "inflow_tph": self.inflow_tph,
                "max_outflow_tph": self.max_outflow_tph, "observed_at": self.observed_at,
                "provenance": self.provenance, "on_demand": self.on_demand, "produced_t": self.produced_t,
                "production_lead_time_hours": self.production_lead_time_hours,
                "production_rate_tph": self.production_rate_tph, "elapsed_hours": self.elapsed_hours}

    @classmethod
    def from_dict(cls, raw: dict) -> "TankState":
        return cls(raw["tank_id"], raw["available"], raw["inventory_t"], dict(raw["properties"]),
                   raw.get("inflow_tph", 0.0), raw.get("max_outflow_tph", 0.0),
                   raw.get("observed_at"), raw.get("provenance", "scenario"),
                   raw.get("on_demand", False), raw.get("produced_t", 0.0),
                   raw.get("production_lead_time_hours", 0.0), raw.get("production_rate_tph", 0.0),
                   raw.get("elapsed_hours", 0.0))
