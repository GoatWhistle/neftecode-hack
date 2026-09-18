"""Tank inventories over the plan: what is actually available, step by step.

A recipe that is fine right now can be impossible an hour later. This module carries the mass
balance forward through the plan so that a blend which would empty a tank mid-horizon is caught
where it fails, not averaged away.

Two rules that are easy to get wrong and are enforced here:

* **Mass is conserved.** Every tonne drawn leaves the tank; replaying the same step twice does
  not spend the stock twice, because each step returns a new state instead of mutating one.
* **The end of the horizon is not the end of the plant.** A plan that survives only by draining
  the reserve to zero at the last point is not feasible: the terminal rule demands a declared
  minimum remaining supply.
"""
from dataclasses import dataclass, field
import math

from neftecode.domain.production.state import TankState
from neftecode.domain.production.scenario import QUALITIES, Scenario

#: Terminal rules a scenario may declare for what must remain at the end of the horizon.
MIN_HOURS_OF_SUPPLY = "min_hours_of_supply"
NO_TERMINAL_RULE = "none"


class InventoryError(ValueError):
    """Raised when a draw is impossible or a scenario's terminal rule is unknown."""


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def initial_state(scenario: Scenario) -> dict[str, TankState]:
    """Tank states at the moment of decision, taken from the scenario."""
    return {t.tank_id: TankState(
        t.tank_id, t.available, t.inventory.value,
        {q: t.property_value(q) for q in QUALITIES},
        t.inflow.value, t.max_outflow.value, provenance="scenario", on_demand=t.on_demand)
        for t in scenario.tanks}


@dataclass(frozen=True)
class DrawResult:
    """Outcome of drawing one step's worth of components."""

    tanks: dict[str, TankState]
    drawn_t: dict[str, float]
    feasible: bool
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {"tanks": {k: v.to_dict() for k, v in self.tanks.items()},
                "drawn_t": dict(self.drawn_t), "feasible": self.feasible,
                "reasons": list(self.reasons)}


def draw_step(tanks: dict[str, TankState], recipe: dict[str, float], throughput_tph: float,
              hours: float, inflow_properties: dict[str, dict[str, float | None]] | None = None) -> DrawResult:
    """Draw one step. Returns a NEW state; the input is never mutated.

    Infeasibility is reported, not raised: the optimiser needs to see why a candidate failed
    so it can propose a different one.
    """
    if not _finite(throughput_tph) or throughput_tph < 0:
        raise InventoryError("Выпуск должен быть конечным и неотрицательным")
    if not _finite(hours) or hours < 0:
        raise InventoryError("Длительность шага должна быть конечной и неотрицательной")
    reasons: list[str] = []
    drawn: dict[str, float] = {}
    updated = dict(tanks)
    for tank_id, fraction in recipe.items():
        if fraction <= 1e-12:
            continue
        if tank_id not in tanks:
            reasons.append(f"Резервуар {tank_id} отсутствует в состоянии")
            continue
        tank = tanks[tank_id]
        rate = throughput_tph * fraction
        mass = rate * hours
        drawn[tank_id] = mass
        if not tank.available:
            reasons.append(f"{tank_id}: резервуар недоступен, отбор невозможен")
            continue
        if rate > tank.max_outflow_tph + 1e-9:
            reasons.append(f"{tank_id}: требуется {rate:.2f} т/ч при пределе отбора "
                           f"{tank.max_outflow_tph:.2f} т/ч")
            continue
        if not tank.on_demand and mass > tank.inventory_t + 1e-9:
            reasons.append(f"{tank_id}: требуется {mass:.2f} т, в наличии {tank.inventory_t:.2f} т")
            continue
        updated[tank_id] = tank.draw(mass)
    # Inflow arrives during the same step for every tank, drawn from or not.
    unknown_inflow: list[str] = []
    for tank_id, tank in updated.items():
        if tank.inflow_tph > 0:
            props = (inflow_properties or {}).get(tank_id, tank.properties)
            if any(props.get(q) is None for q in QUALITIES):
                unknown_inflow.extend(q for q in QUALITIES if props.get(q) is None)
            updated[tank_id] = tank.mix_in(tank.inflow_tph * hours, props)
    if unknown_inflow:
        reasons.append("Приток содержит неизвестные свойства: " + ", ".join(dict.fromkeys(unknown_inflow)))
    return DrawResult(updated, drawn, not reasons, tuple(dict.fromkeys(reasons)))


@dataclass
class InventoryLedger:
    """Runs a whole plan through the tanks and states where it first becomes impossible."""

    scenario: Scenario
    tanks: dict[str, TankState] = field(init=False)

    def __post_init__(self):
        self.tanks = initial_state(self.scenario)

    def terminal_rule(self) -> tuple[str, float]:
        policy = self.scenario.policy or {}
        rule = policy.get("terminal_inventory_rule", NO_TERMINAL_RULE)
        if rule not in (MIN_HOURS_OF_SUPPLY, NO_TERMINAL_RULE):
            raise InventoryError(f"policy.terminal_inventory_rule: неизвестное правило «{rule}»")
        return rule, float(policy.get("terminal_min_hours", 0.0))

    def run_plan(self, steps, inflow_properties=None) -> dict:
        """Walk the plan. `steps` are `(time_hours, recipe, throughput_tph)` in order.

        The mass of each step is the throughput held until the next step's time; the last step
        is held to the scenario horizon.
        """
        times = [float(t) for t, _, _ in steps]
        if times != sorted(times):
            raise InventoryError("Шаги плана должны идти по возрастанию времени")
        horizon = self.scenario.horizon.hours
        tanks = dict(self.tanks)
        timeline = []
        first_failure = None
        for index, (time_hours, recipe, throughput) in enumerate(steps):
            until = times[index + 1] if index + 1 < len(times) else horizon
            duration = max(0.0, until - time_hours)
            start_inventories = {k: v.inventory_t for k, v in tanks.items()}
            start_properties = {k: dict(v.properties) for k, v in tanks.items()}
            props = (inflow_properties or {}).get(time_hours, {})
            result = draw_step(tanks, recipe, throughput, duration, props)
            tanks = result.tanks
            visible_properties = {k: dict(v.properties) for k, v in tanks.items()}
            timeline.append({"time_hours": time_hours, "duration_hours": duration,
                             "drawn_t": result.drawn_t, "feasible": result.feasible,
                             "reasons": list(result.reasons),
                             "inventories": start_inventories,
                             "properties": start_properties,
                             "end_inventories": {k: v.inventory_t for k, v in tanks.items()},
                             "end_properties": visible_properties,
                             "unknown_inflow": list(result.reasons)})
            if not result.feasible and first_failure is None:
                first_failure = {"time_hours": time_hours, "reasons": list(result.reasons)}
        terminal = self.check_terminal(tanks, steps[-1][2] if steps else 0.0,
                                       steps[-1][1] if steps else {})
        return {"timeline": timeline, "final_inventories": {k: v.inventory_t for k, v in tanks.items()},
                "feasible": first_failure is None and terminal["satisfied"],
                "first_failure": first_failure, "terminal": terminal,
                "rule": "Остаток проверяется на каждом шаге и отдельно в конце горизонта, чтобы план "
                        "не выигрывал за счёт опустошения резерва к последней точке."}

    def check_terminal(self, tanks: dict[str, TankState], throughput_tph: float,
                       recipe: dict[str, float]) -> dict:
        """Would the last recipe still be sustainable just past the horizon?"""
        rule, hours = self.terminal_rule()
        if rule == NO_TERMINAL_RULE or hours <= 0:
            return {"rule": NO_TERMINAL_RULE, "satisfied": True,
                    "reason": "Правило остатка на конце горизонта сценарием не задано"}
        shortfalls = []
        for tank_id, fraction in (recipe or {}).items():
            if fraction <= 1e-12 or tank_id not in tanks or tanks[tank_id].on_demand:
                continue
            needed = throughput_tph * fraction * hours
            available = tanks[tank_id].inventory_t
            if needed > available + 1e-9:
                shortfalls.append(f"{tank_id}: на {hours:g} ч после горизонта нужно {needed:.2f} т, "
                                  f"останется {available:.2f} т")
        return {"rule": rule, "min_hours": hours, "satisfied": not shortfalls,
                "reason": "; ".join(shortfalls) or
                          f"Остатка хватает ещё на {hours:g} ч текущего рецепта",
                "shortfalls": shortfalls}
