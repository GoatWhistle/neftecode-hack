from dataclasses import dataclass, replace

from neftecode.domain.shared.primitives import (
    ContractError,
    QUALITIES,
    _clean_number,
    _finite,
    volume_additive_density,
)


AVAILABLE = "available"
FILLING = "filling"
AWAITING_PASSPORT = "awaiting_passport"
READY = "ready"
DRAINING = "draining"
PARK_STATUSES = (AVAILABLE, FILLING, AWAITING_PASSPORT, READY, DRAINING)
EPSILON = 1e-9


def capacity_tonnes(volume_m3: float, density_kgm3: float) -> float:
    if not _finite(volume_m3) or volume_m3 <= 0:
        raise ContractError("tank.volume_m3: ожидается положительный конечный объём")
    if not _finite(density_kgm3) or density_kgm3 <= 0:
        raise ContractError("tank.density_kgm3: ожидается положительная конечная плотность")
    return volume_m3 * density_kgm3 / 1000.0


def _empty_properties() -> dict[str, None]:
    return {name: None for name in QUALITIES}


@dataclass(frozen=True)
class ParkTankState:
    tank_id: str
    capacity_t: float
    mass_t: float
    properties: dict[str, float | None]
    status: str = AVAILABLE
    batch_id: str | None = None
    status_elapsed_h: float = 0.0
    batch_age_h: float = 0.0
    passport_duration_h: float = 12.0
    nominal_drain_h: float = 24.0
    provenance: str = "scenario"
    initial_uncertainty: tuple[str, ...] = ()

    def __post_init__(self):
        where = f"ParkTankState[{self.tank_id}]"
        if not isinstance(self.tank_id, str) or not self.tank_id.strip():
            raise ContractError("ParkTankState.tank_id: нужен непустой идентификатор")
        for name, value, allow_zero in (
            ("capacity_t", self.capacity_t, False),
            ("mass_t", self.mass_t, True),
            ("status_elapsed_h", self.status_elapsed_h, True),
            ("batch_age_h", self.batch_age_h, True),
            ("passport_duration_h", self.passport_duration_h, False),
            ("nominal_drain_h", self.nominal_drain_h, False),
        ):
            if not _finite(value) or value < 0 or (not allow_zero and value == 0):
                raise ContractError(f"{where}.{name}: ожидается положительное конечное значение")
        if self.mass_t > self.capacity_t + EPSILON:
            raise ContractError(f"{where}: масса {self.mass_t:.3f} т превышает вместимость {self.capacity_t:.3f} т")
        if self.status not in PARK_STATUSES:
            raise ContractError(f"{where}.status: неизвестное состояние {self.status!r}")
        if self.status == AVAILABLE and (self.mass_t > EPSILON or self.batch_id is not None):
            raise ContractError(f"{where}: доступный резервуар должен быть пуст и не иметь партии")
        if self.status != AVAILABLE and (not isinstance(self.batch_id, str) or not self.batch_id.strip()):
            raise ContractError(f"{where}: для состояния {self.status} обязателен batch_id")
        cleaned = {name: _clean_number(self.properties.get(name), f"{where}.{name}") for name in QUALITIES}
        object.__setattr__(self, "properties", cleaned)
        object.__setattr__(self, "initial_uncertainty", tuple(dict.fromkeys(self.initial_uncertainty)))

    @property
    def nominal_drain_tph(self) -> float:
        return self.capacity_t / self.nominal_drain_h

    @property
    def passport_ready_in_h(self) -> float | None:
        if self.status == AWAITING_PASSPORT:
            return max(0.0, self.passport_duration_h - self.status_elapsed_h)
        return 0.0 if self.status in (READY, DRAINING) else None

    def start_filling(self, batch_id: str) -> "ParkTankState":
        if self.status != AVAILABLE:
            raise ContractError(f"{self.tank_id}: новый налив разрешён только из available")
        return replace(self, status=FILLING, batch_id=batch_id, status_elapsed_h=0.0,
                       batch_age_h=0.0, properties=_empty_properties())

    def fill(self, mass_t: float, properties: dict[str, float | None], hours: float = 0.0) -> "ParkTankState":
        if self.status != FILLING:
            raise ContractError(f"{self.tank_id}: приток разрешён только при filling")
        if not _finite(mass_t) or mass_t < 0 or not _finite(hours) or hours < 0:
            raise ContractError(f"{self.tank_id}: масса и время налива должны быть конечными и неотрицательными")
        total = self.mass_t + mass_t
        if total > self.capacity_t + EPSILON:
            raise ContractError(f"{self.tank_id}: налив переполняет резервуар ({total:.3f} > {self.capacity_t:.3f} т)")
        merged = dict(self.properties)
        if mass_t > EPSILON:
            for name in QUALITIES:
                incoming, current = properties.get(name), self.properties.get(name)
                if incoming is None or not _finite(incoming) or (self.mass_t > EPSILON and current is None):
                    merged[name] = None
                elif self.mass_t <= EPSILON:
                    merged[name] = incoming
                elif name == "density_kgm3":
                    merged[name] = volume_additive_density(
                        {"stock": self.mass_t, "inflow": mass_t}, {"stock": current, "inflow": incoming})
                else:
                    merged[name] = (self.mass_t * current + mass_t * incoming) / total
        updated = replace(self, mass_t=min(total, self.capacity_t), properties=merged,
                          status_elapsed_h=self.status_elapsed_h + hours,
                          batch_age_h=self.batch_age_h + hours)
        return updated.finish_filling() if total >= self.capacity_t - EPSILON else updated

    def finish_filling(self) -> "ParkTankState":
        if self.status != FILLING or self.mass_t <= EPSILON:
            raise ContractError(f"{self.tank_id}: завершить можно только непустой налив")
        return replace(self, status=AWAITING_PASSPORT, status_elapsed_h=0.0)

    def advance(self, hours: float) -> "ParkTankState":
        if not _finite(hours) or hours < 0:
            raise ContractError(f"{self.tank_id}: время должно быть конечным и неотрицательным")
        if hours == 0 or self.status == AVAILABLE:
            return self
        elapsed = self.status_elapsed_h + hours
        age = self.batch_age_h + hours
        if self.status == AWAITING_PASSPORT and elapsed >= self.passport_duration_h - EPSILON:
            return replace(self, status=READY, status_elapsed_h=max(0.0, elapsed - self.passport_duration_h),
                           batch_age_h=age)
        return replace(self, status_elapsed_h=elapsed, batch_age_h=age)

    def start_draining(self) -> "ParkTankState":
        if self.status != READY:
            raise ContractError(f"{self.tank_id}: слив разрешён только для готовой паспортизованной партии")
        return replace(self, status=DRAINING, status_elapsed_h=0.0)

    def drain(self, demand_tph: float, hours: float) -> tuple["ParkTankState", float]:
        if self.status != DRAINING:
            raise ContractError(f"{self.tank_id}: отбор разрешён только при draining")
        if not _finite(demand_tph) or demand_tph < 0 or not _finite(hours) or hours < 0:
            raise ContractError(f"{self.tank_id}: спрос и время должны быть конечными и неотрицательными")
        drawn = min(self.mass_t, demand_tph * hours, self.nominal_drain_tph * hours)
        remaining = max(0.0, self.mass_t - drawn)
        if remaining <= EPSILON:
            return replace(self, mass_t=0.0, properties=_empty_properties(), status=AVAILABLE,
                           batch_id=None, status_elapsed_h=0.0, batch_age_h=0.0), drawn
        return replace(self, mass_t=remaining, status_elapsed_h=self.status_elapsed_h + hours,
                       batch_age_h=self.batch_age_h + hours), drawn

    def to_dict(self) -> dict:
        return {
            "tank_id": self.tank_id, "capacity_t": self.capacity_t, "mass_t": self.mass_t,
            "properties": dict(self.properties), "status": self.status, "batch_id": self.batch_id,
            "status_elapsed_h": self.status_elapsed_h, "batch_age_h": self.batch_age_h,
            "passport_duration_h": self.passport_duration_h, "passport_ready_in_h": self.passport_ready_in_h,
            "nominal_drain_h": self.nominal_drain_h, "nominal_drain_tph": self.nominal_drain_tph,
            "provenance": self.provenance, "initial_uncertainty": list(self.initial_uncertainty),
        }


@dataclass(frozen=True)
class ParkState:
    tanks: tuple[ParkTankState, ...]
    elapsed_h: float = 0.0
    total_in_t: float = 0.0
    total_out_t: float = 0.0
    initial_mass_t: float | None = None
    model_version: str = "tank-park/1"

    def __post_init__(self):
        if not self.tanks or len({tank.tank_id for tank in self.tanks}) != len(self.tanks):
            raise ContractError("ParkState.tanks: нужен непустой список с уникальными tank_id")
        for name in ("elapsed_h", "total_in_t", "total_out_t"):
            value = getattr(self, name)
            if not _finite(value) or value < 0:
                raise ContractError(f"ParkState.{name}: ожидается конечное неотрицательное значение")
        if self.initial_mass_t is None:
            object.__setattr__(self, "initial_mass_t", self.mass_t)
        expected = self.initial_mass_t + self.total_in_t - self.total_out_t
        if abs(self.mass_t - expected) > 1e-6:
            raise ContractError(f"ParkState: нарушен массовый баланс ({self.mass_t:.6f} != {expected:.6f} т)")

    @property
    def mass_t(self) -> float:
        return sum(tank.mass_t for tank in self.tanks)

    def tank(self, tank_id: str) -> ParkTankState:
        for tank in self.tanks:
            if tank.tank_id == tank_id:
                return tank
        raise ContractError(f"ParkState: резервуар {tank_id} отсутствует")

    def evolve(self, tanks: tuple[ParkTankState, ...], *, inflow_t: float = 0.0,
               outflow_t: float = 0.0, hours: float = 0.0) -> "ParkState":
        if {tank.tank_id for tank in tanks} != {tank.tank_id for tank in self.tanks}:
            raise ContractError("ParkState.evolve: набор резервуаров нельзя менять при переходе")
        return replace(self, tanks=tanks, elapsed_h=self.elapsed_h + hours,
                       total_in_t=self.total_in_t + inflow_t, total_out_t=self.total_out_t + outflow_t)

    def replace_tank(self, updated: ParkTankState, *, inflow_t: float = 0.0,
                     outflow_t: float = 0.0, hours: float = 0.0) -> "ParkState":
        if updated.tank_id not in {tank.tank_id for tank in self.tanks}:
            raise ContractError(f"ParkState: резервуар {updated.tank_id} отсутствует")
        tanks = tuple(updated if tank.tank_id == updated.tank_id else tank for tank in self.tanks)
        return self.evolve(tanks, inflow_t=inflow_t, outflow_t=outflow_t, hours=hours)

    def to_dict(self) -> dict:
        return {"model_version": self.model_version, "elapsed_h": self.elapsed_h,
                "initial_mass_t": self.initial_mass_t, "mass_t": self.mass_t,
                "total_in_t": self.total_in_t, "total_out_t": self.total_out_t,
                "balance_error_t": self.mass_t - self.initial_mass_t - self.total_in_t + self.total_out_t,
                "tanks": [tank.to_dict() for tank in self.tanks]}
