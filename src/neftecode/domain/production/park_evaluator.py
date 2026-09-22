from dataclasses import dataclass, field

from neftecode.domain.production.park import (
    AVAILABLE,
    AWAITING_PASSPORT,
    DRAINING,
    FILLING,
    READY,
    ParkState,
    ParkTankState,
    capacity_tonnes,
)
from neftecode.domain.shared.primitives import ContractError, QUALITIES


def initial_park(config, properties: dict[str, float | None], inflow_tph: float) -> ParkState:
    if inflow_tph <= 0:
        raise ContractError("tank_park: для расчёта фаз нужен положительный приток")
    capacity = capacity_tonnes(config.capacity_m3, config.density_kgm3)
    fill_h = capacity / inflow_tph
    process_h = fill_h + config.passport_duration_h + config.nominal_drain_h
    cycle_h = max(config.tank_count * fill_h, process_h)
    tanks = []
    for index, declared_phase in enumerate(config.phase_offsets_h, start=1):
        phase = declared_phase % cycle_h
        common = dict(tank_id=f"{config.component_tank_id}-{index}", capacity_t=capacity,
                      passport_duration_h=config.passport_duration_h,
                      nominal_drain_h=config.nominal_drain_h, provenance=config.source)
        batch_id = f"{config.component_tank_id}-batch-{index}"
        if phase < fill_h:
            mass = inflow_tph * phase
            values = dict(properties) if mass > 1e-9 else {name: None for name in QUALITIES}
            tank = ParkTankState(**common, mass_t=mass, properties=values, status=FILLING,
                                 batch_id=batch_id, status_elapsed_h=phase, batch_age_h=phase)
        elif phase < fill_h + config.passport_duration_h:
            elapsed = phase - fill_h
            tank = ParkTankState(**common, mass_t=capacity, properties=dict(properties),
                                 status=AWAITING_PASSPORT, batch_id=batch_id,
                                 status_elapsed_h=elapsed, batch_age_h=phase)
        elif phase < process_h:
            elapsed = phase - fill_h - config.passport_duration_h
            mass = max(0.0, capacity - capacity / config.nominal_drain_h * elapsed)
            if mass <= 1e-9:
                tank = ParkTankState(**common, mass_t=0.0, properties={name: None for name in QUALITIES})
            else:
                tank = ParkTankState(**common, mass_t=mass, properties=dict(properties), status=DRAINING,
                                     batch_id=batch_id, status_elapsed_h=elapsed, batch_age_h=phase)
        else:
            tank = ParkTankState(**common, mass_t=0.0, properties={name: None for name in QUALITIES})
        tanks.append(tank)
    return ParkState(tuple(tanks))


@dataclass(frozen=True)
class TankOperation:
    inflow_tph: float = 0.0
    inflow_properties: dict[str, float | None] = field(default_factory=dict)
    batch_id: str | None = None
    finish_filling: bool = False
    start_draining: bool = False
    demand_tph: float = 0.0


@dataclass(frozen=True)
class ParkStep:
    duration_h: float
    operations: dict[str, TankOperation] = field(default_factory=dict)
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class ParkFrame:
    time_h: float
    state: ParkState
    inflow_t: float
    outflow_t: float
    inflow_by_tank: dict[str, float] = field(default_factory=dict)
    outflow_by_tank: dict[str, float] = field(default_factory=dict)
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {"time_h": self.time_h, "inflow_t": self.inflow_t, "outflow_t": self.outflow_t,
                "inflow_by_tank": dict(self.inflow_by_tank), "outflow_by_tank": dict(self.outflow_by_tank),
                "reasons": list(self.reasons), "state": self.state.to_dict()}


@dataclass(frozen=True)
class ParkTrajectory:
    frames: tuple[ParkFrame, ...]
    feasible: bool
    reasons: tuple[str, ...]
    model_version: str = "tank-park/1"

    @property
    def terminal(self) -> ParkState:
        return self.frames[-1].state

    def to_dict(self) -> dict:
        return {"model_version": self.model_version, "feasible": self.feasible,
                "reasons": list(self.reasons), "frames": [frame.to_dict() for frame in self.frames],
                "terminal": self.terminal.to_dict()}


class ParkEvaluator:

    model_version = "tank-park/1"

    def evaluate(self, initial: ParkState, steps: list[ParkStep] | tuple[ParkStep, ...]) -> ParkTrajectory:
        state = initial
        frames = [ParkFrame(state.elapsed_h, state, 0.0, 0.0)]
        all_reasons: list[str] = []
        for index, step in enumerate(steps):
            if step.duration_h < 0:
                raise ContractError(f"ParkStep[{index}].duration_h: время не может быть отрицательным")
            unknown = set(step.operations) - {tank.tank_id for tank in state.tanks}
            if unknown:
                raise ContractError(f"ParkStep[{index}]: неизвестные резервуары {', '.join(sorted(unknown))}")
            updated, inflow, outflow, reasons = [], 0.0, 0.0, list(step.reasons)
            inflow_by_tank, outflow_by_tank = {}, {}
            for tank in state.tanks:
                operation = step.operations.get(tank.tank_id, TankOperation())
                try:
                    next_tank, received, drawn = self._transition(tank, operation, step.duration_h)
                except ContractError as exc:
                    next_tank, received, drawn = tank.advance(step.duration_h), 0.0, 0.0
                    reasons.append(str(exc))
                updated.append(next_tank)
                inflow += received
                outflow += drawn
                if received > 0:
                    inflow_by_tank[tank.tank_id] = received
                if drawn > 0:
                    outflow_by_tank[tank.tank_id] = drawn
            state = state.evolve(tuple(updated), inflow_t=inflow, outflow_t=outflow, hours=step.duration_h)
            all_reasons.extend(reasons)
            frames.append(ParkFrame(state.elapsed_h, state, inflow, outflow,
                                    inflow_by_tank, outflow_by_tank, tuple(reasons)))
        unique = tuple(dict.fromkeys(all_reasons))
        return ParkTrajectory(tuple(frames), not unique, unique, self.model_version)

    @staticmethod
    def _transition(tank: ParkTankState, operation: TankOperation,
                    duration_h: float) -> tuple[ParkTankState, float, float]:
        if operation.inflow_tph < 0 or operation.demand_tph < 0:
            raise ContractError(f"{tank.tank_id}: расходы должны быть неотрицательными")
        if operation.inflow_tph > 0 and operation.demand_tph > 0:
            raise ContractError(f"{tank.tank_id}: одновременные налив и слив запрещены")
        current = tank
        if current.status == AVAILABLE and operation.inflow_tph > 0:
            if not operation.batch_id:
                raise ContractError(f"{tank.tank_id}: для нового налива нужен batch_id")
            current = current.start_filling(operation.batch_id)
        if operation.start_draining:
            current = current.start_draining()
        if operation.finish_filling:
            current = current.finish_filling()

        inflow = operation.inflow_tph * duration_h
        if inflow > 0:
            current = current.fill(inflow, operation.inflow_properties, hours=duration_h)
            return current, inflow, 0.0
        if current.status == DRAINING:
            current, outflow = current.drain(operation.demand_tph, duration_h)
            return current, 0.0, outflow
        if operation.demand_tph > 0:
            raise ContractError(f"{tank.tank_id}: спрос задан для резервуара в состоянии {current.status}")
        if current.status in (FILLING, AWAITING_PASSPORT, READY):
            current = current.advance(duration_h)
        return current, 0.0, 0.0
