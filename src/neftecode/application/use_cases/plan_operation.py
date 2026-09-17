"""Short plans over the horizon: the transitional blend while the hydrotreater catches up.

The situation this exists for: crude worsens, a hydrotreating correction is the right answer,
but it takes hours to act. Meanwhile the product still has to meet spec. So a plan holds a
richer blend during the transition and steps back once the correction has taken effect.

What the planner is careful about:

* **A proposal is not an execution.** A plan's own steps are evaluated as *if* executed; what
  actually reached the plant comes in as confirmed `PendingAction`s from the caller. Running
  the advisor twice does not make the advice happen.
* **No flip-flopping.** A change is only proposed if it clears the scenario's minimum useful
  benefit, and a plan is not allowed to undo a confirmed action that has not yet had time
  to show its effect.
* **Stocks are real.** Every step draws from the tanks, so a transitional blend that would
  outlast the reserve is rejected where it fails.
"""
from dataclasses import dataclass, field, replace
import math

from neftecode.domain.production.blending import Blender
from neftecode.domain.production.economics import Economics
from neftecode.domain.advisory.gate import TrajectoryPoint, check_plan
from neftecode.domain.advisory.entities import PlanStep
from neftecode.domain.production.inventory import InventoryLedger
from neftecode.domain.advisory.optimizer import Candidate, CandidateGenerator, Evaluation, rank
from neftecode.domain.production.process import ChainModel
from neftecode.domain.production.scenario import Scenario
from neftecode.application.contracts import PlanningCommand, PlanningResult


class PlannerError(ValueError):
    """Raised when a plan is structurally impossible to evaluate."""


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


@dataclass(frozen=True)
class PlanCandidate:
    """A sequence of steps, plus how many of them actually change anything."""

    plan_id: str
    steps: tuple[PlanStep, ...]
    changes: int = 0
    intent: str = ""

    def immediate(self) -> PlanStep:
        return self.steps[0]

    def to_dict(self) -> dict:
        return {"plan_id": self.plan_id, "intent": self.intent, "changes": self.changes,
                "steps": [s.to_advice_dict() for s in self.steps]}


@dataclass
class PlanOperation:
    """Builds short plans and evaluates each one end to end through the same core."""

    scenario: Scenario
    chain: ChainModel = field(init=False)
    blender: Blender = field(init=False)
    economics: Economics = field(init=False)

    def __post_init__(self):
        self.chain = ChainModel(self.scenario)
        self.blender = Blender(self.scenario)
        self.economics = Economics(self.scenario)

    # --- Building plans ---

    def grid(self) -> list[float]:
        return self.scenario.horizon.times_hours()

    def base_controls(self) -> dict[str, float]:
        return self.chain.current_controls()

    def confirmed_with_operation(self, confirmed=(), current_operation=None):
        """A saved operating point is settled unless an explicit pending action dates it."""
        confirmed = tuple(confirmed)
        if current_operation is None:
            return confirmed
        dated = {name for _, controls in confirmed for name in controls}
        base = self.base_controls()
        standing = {k: v for k, v in current_operation["controls"].items()
                    if k not in dated and abs(v - base.get(k, v)) > 1e-9}
        age = max(stage.response_lag_hours.value for stage in self.scenario.stages.values())
        return ((-age, standing),) + confirmed if standing else confirmed

    def inflow_properties(self, time_hours: float, pending=()) -> dict[str, dict[str, float | None]]:
        """Properties of the stream entering the main tank at a relative time."""
        incoming = self.chain.run_at(time_hours, pending)
        tank = self.scenario.tank(self._main_id())
        sulfur = incoming.sulfur_mgkg if tank.sulfur_from_chain else tank.property_value("sulfur_mgkg")
        declared = tank.properties.get("sulfur_mgkg")
        if tank.inflow_sulfur is not None:
            # A forecast of the hydrotreated stream enters the tank; the action model shifts it.
            ratio = self._response_ratio(time_hours, pending)
            sulfur = None if ratio is None else tank.inflow_sulfur.value * ratio
        elif declared is not None and declared.source in ("derived", "measured"):
            level = self._main_sulfur()
            ratio = self._response_ratio(time_hours, pending)
            sulfur = None if level is None or ratio is None else level * ratio
        # The chain does not model diesel density; the inflow keeps the component's declared density.
        return {self._main_id(): {"sulfur_mgkg": sulfur, "t95_c": incoming.t95_c,
                                 "cetane_number": tank.property_value("cetane_number"),
                                 "density_kgm3": tank.property_value("density_kgm3")}}

    def build_plans(self, budget: int = 120, current_operation: dict | None = None) -> tuple[list[PlanCandidate], dict]:
        """Single-step plans plus transitional two-phase plans, in a fixed order."""
        generator_scenario = self.scenario
        base = self.base_controls()
        if current_operation is not None:
            base = {**base, **current_operation["controls"]}
            stages = {key: replace(stage, controls={
                name: {**spec, "current": replace(spec["current"], value=base[name])}
                for name, spec in stage.controls.items()})
                for key, stage in self.scenario.stages.items()}
            operation = replace(self.scenario.current_operation,
                                recipe=dict(current_operation["recipe"]),
                                throughput=replace(self.scenario.current_operation.throughput,
                                                   value=current_operation["throughput_tph"]))
            generator_scenario = replace(self.scenario, stages=stages, current_operation=operation)
        generator = CandidateGenerator(generator_scenario, budget=budget)
        singles, info = generator.generate()
        if current_operation is not None:
            dose = current_operation.get("additive_dose", 0.0)
            singles = [replace(c, additive_dose=dose) if c.candidate_id == "hold" else
                       replace(c, changes=c.changes - int(c.additive_dose != 0.0)
                               + int(abs(c.additive_dose - dose) > 1e-9)) for c in singles]
        plans: list[PlanCandidate] = []
        for candidate in singles:
            plans.append(PlanCandidate(
                candidate.candidate_id,
                (PlanStep(0.0, dict(candidate.controls), dict(candidate.recipe),
                              candidate.throughput_tph, candidate.additive_dose),),
                candidate.changes,
                "постоянный режим на весь горизонт"))

        # Transitional plans: a correction now, a richer blend until it acts, then step back.
        # Throughput is varied here too: a transitional plan pinned to one throughput would
        # fail on an outflow limit and never be compared on its merits.
        lag = self.scenario.stages["hydrotreating"].response_lag_hours.value
        switch = min(self.scenario.horizon.hours, lag)
        if switch > 0:
            corrections = [c for c in singles
                           if c.changes == 1 and c.candidate_id != "hold" and c.additive_dose == 0.0]
            corrections = self._distinct_corrections(corrections, base)
            throughputs = sorted({c.throughput_tph for c in singles})
            relief_step = float(self.scenario.policy.get("relief_step", 0.1))
            reliefs = [round(relief_step * i, 6) for i in range(1, int(0.6 / relief_step) + 1)]
            for correction in corrections:
                for throughput in throughputs:
                    for relief in reliefs:
                        if len(plans) >= budget * 4:
                            break
                        plans.append(PlanCandidate(
                            f"t{len(plans):04d}",
                            (PlanStep(0.0, dict(correction.controls),
                                          self._recipe_with_reserve(relief), throughput, 0.0),
                             PlanStep(switch, dict(correction.controls),
                                          self._recipe_with_reserve(max(0.0, relief - relief_step)),
                                          throughput, 0.0)),
                            correction.changes + 1,
                            f"временная помощь смешением до эффекта коррекции через {switch:g} ч"))
        info["plans"] = len(plans)
        return plans, info

    @staticmethod
    def _distinct_corrections(candidates, base: dict[str, float]):
        """One representative per moved setpoint value, in a fixed order."""
        seen, out = set(), []
        for candidate in candidates:
            moved = tuple(sorted((k, v) for k, v in candidate.controls.items()
                                 if abs(v - base[k]) > 1e-9))
            if moved and moved not in seen:
                seen.add(moved)
                out.append(candidate)
        return out

    def _reserve_id(self) -> str:
        tanks = self.scenario.available_tanks()
        return tanks[1].tank_id if len(tanks) > 1 else tanks[0].tank_id

    def _recipe_with_reserve(self, fraction: float) -> dict[str, float]:
        tanks = [t.tank_id for t in self.scenario.available_tanks()]
        if len(tanks) == 1:
            return {tanks[0]: 1.0}
        return {tanks[0]: round(1.0 - fraction, 6), tanks[1]: round(fraction, 6),
                **{t: 0.0 for t in tanks[2:]}}

    # --- Evaluating one plan ---

    def evaluate(self, plan: PlanCandidate, confirmed=(), initial_tanks=None, current_operation=None) -> Evaluation:
        """Run the plan through the chain, the blender, the tanks and the gate.

        `confirmed` carries operator-confirmed actions as `(applied_at_hours, controls)`. The
        plan's own steps are treated as proposals: they shape the trajectory being evaluated,
        but they never enter `confirmed` on their own.
        """
        times = [s.time_hours for s in plan.steps]
        if times != sorted(times) or times[0] != 0.0:
            raise PlannerError(f"{plan.plan_id}: шаги плана должны начинаться в 0 ч и возрастать")
        confirmed = self.confirmed_with_operation(confirmed, current_operation)
        ledger = InventoryLedger(self.scenario)
        if initial_tanks is not None:
            ledger.tanks = dict(initial_tanks)
        # A plan step carries its DELTA from the scenario baseline, not a full set of setpoints.
        # Otherwise a plan that does not touch a control would silently revert a correction the
        # operator has already confirmed.
        baseline = self.base_controls()
        for _, controls in sorted(confirmed, key=lambda item: item[0]):
            baseline.update(controls)
        if current_operation is not None:
            baseline.update(current_operation["controls"])
        deltas = []
        for step in plan.steps:
            delta = {k: v for k, v in step.controls.items() if abs(v - baseline.get(k, v)) > 1e-9}
            if delta:
                deltas.append((step.time_hours, delta))
            baseline.update(step.controls)
        pending = tuple(confirmed) + tuple(deltas)

        trajectory: list[TrajectoryPoint] = []
        costs = []
        severities = []
        grid = self.grid()
        ledger_steps = [(t, self._active_step(plan, t).recipe,
                         self._active_step(plan, t).throughput_tph) for t in grid]
        inflow_properties = {}
        for t in grid:
            inflow_properties[t] = self.inflow_properties(t, pending)
        stock = ledger.run_plan(ledger_steps, inflow_properties)
        inventories_at = {entry["time_hours"]: entry["inventories"] for entry in stock["timeline"]}
        for index, time_hours in enumerate(grid):
            spec = self._active_step(plan, time_hours)
            stream = self.chain.run_at(time_hours, pending)
            properties = stock["timeline"][index]["properties"]
            blend = self.blender.blend(spec.recipe, spec.throughput_tph,
                                       hours=self._duration(grid, index),
                                       additive_dose=spec.additive_dose,
                                       property_overrides=properties)
            qualities = dict(blend.qualities)
            inventories = self._inventories_at(stock, time_hours)
            reasons = self._reasons_at(stock, time_hours)
            trajectory.append(TrajectoryPoint(
                time_hours=time_hours, qualities=qualities, inventories=inventories,
                production_tph=spec.throughput_tph, controls=self._effective_controls(time_hours, pending),
                recipe=spec.recipe, throughput_tph=spec.throughput_tph,
                additive_dose=spec.additive_dose, applicability=stream.applicability,
                inventory_reasons=reasons))
            costs.append(self.economics.step_cost(
                spec.recipe, spec.throughput_tph, self._duration(grid, index),
                spec.additive_dose, trajectory[-1].controls.get("ht_reactor_inlet_temp_c")))
            severity = self.economics.severity(trajectory[-1].controls)
            severities.append(severity["index"] if severity["available"] else None)

        gate = check_plan(plan.plan_id, trajectory, self.scenario, stock["terminal"])
        summary = self.economics.summarise(costs)
        known = [s for s in severities if s is not None]
        return Evaluation(
            Candidate(plan.plan_id, dict(plan.steps[0].controls), dict(plan.steps[0].recipe),
                      plan.steps[0].throughput_tph, plan.steps[0].additive_dose, plan.changes),
            gate, summary["production_t"], summary["cost_per_tonne"],
            max(known) if known else None)

    def lookahead(self, plan: PlanCandidate, hours: float, confirmed=(), initial_tanks=None,
                  current_operation=None) -> dict:
        """Continue a plan past the horizon and report when product quality would first fail.

        The forecast is not extended: the same stock and blend calculation runs on, the last plan
        step is held, and the inflow keeps its end-of-horizon properties. The projection stops where
        a stock runs out, because past that point the recipe itself is no longer possible.
        """
        if not _finite(hours) or hours <= 0:
            raise PlannerError("lookahead: длительность должна быть положительной")
        base = self.scenario.horizon.hours
        extended = replace(self.scenario, horizon=replace(self.scenario.horizon, hours=base + hours))
        evaluation = PlanOperation(extended).evaluate(plan, confirmed, initial_tanks=initial_tanks,
                                                      current_operation=current_operation)
        checks = [c for c in evaluation.gate.checks if c.time_hours is not None]
        stock_ends = min((c.time_hours for c in checks if c.status == "fail"
                          and (c.constraint_id.startswith("inventory.") or c.constraint_id.startswith("outflow."))
                          and c.constraint_id != "inventory.terminal"), default=None)
        violations = sorted((c for c in checks if c.constraint_id.startswith("quality.") and c.status == "fail"
                             and (stock_ends is None or c.time_hours < stock_ends)),
                            key=lambda c: c.time_hours)
        first = violations[0] if violations else None
        return {
            "plan_id": plan.plan_id, "lookahead_hours": hours,
            "projected_until_hours": stock_ends if stock_ends is not None else base + hours,
            "stock_ends_at_hours": stock_ends,
            "hours_to_violation": first.time_hours if first else None,
            "constraint": first.constraint_id if first else None,
            "observed": first.observed if first else None,
            "limit": first.limit if first else None,
            "assumption": ("За горизонтом прогноз не продлевается: план держит последний шаг, приток — свойства "
                           "конца горизонта, расчёт останавливается при исчерпании запаса."),
        }

    def _effective_controls(self, time_hours: float, pending) -> dict[str, float]:
        """Setpoints actually acting at this time: the baseline updated by what is in effect."""
        controls = dict(self.base_controls())
        avt_lag = self.scenario.stages["avt"].response_lag_hours.value
        ht_lag = self.scenario.stages["hydrotreating"].response_lag_hours.value
        avt_names = set(self.scenario.stages["avt"].controls)
        for at, moves in sorted(pending, key=lambda item: item[0]):
            for name, value in moves.items():
                lag = avt_lag if name in avt_names else ht_lag
                if at + lag <= time_hours + 1e-9:
                    controls[name] = value
        return controls

    def _response_ratio(self, time_hours: float, pending) -> float | None:
        """How much the action model shifts hydrotreated sulfur relative to doing nothing."""
        acting = self.chain.run_at(time_hours, pending)
        idle = self.chain.run_at(time_hours, ())
        if acting.sulfur_mgkg is None or idle.sulfur_mgkg is None or idle.sulfur_mgkg <= 0:
            return None
        return acting.sulfur_mgkg / idle.sulfur_mgkg

    def _main_id(self) -> str:
        for tank in self.scenario.tanks:
            if tank.tank_id == "main" or tank.sulfur_from_chain:
                return tank.tank_id
        return self.scenario.tanks[0].tank_id

    def _main_sulfur(self) -> float | None:
        """Current level of the main component's sulfur, or None when it cannot be known.

        Either the chain produces it (so crude quality and the standing regime reach the
        decision), or the scenario declares it — for instance because a trained forecast was
        bound into it, which outranks the model.

        When the scenario says the level comes from the chain and the chain cannot produce it,
        the answer is unknown. Falling back to the standing constant would substitute a
        placeholder the scenario itself calls a reference value, and the gate would see a
        number where it must see `unknown`.
        """
        tank = self.scenario.tank(self._main_id())
        if tank.sulfur_from_chain:
            return self.chain.run_at(0.0, ()).sulfur_mgkg
        return tank.property_value("sulfur_mgkg")

    def _avt_controls(self, spec: PlanStep) -> dict[str, float]:
        names = set(self.scenario.stages["avt"].controls)
        return {k: v for k, v in spec.controls.items() if k in names}

    @staticmethod
    def _duration(grid, index) -> float:
        return grid[index + 1] - grid[index] if index + 1 < len(grid) else 0.0

    @staticmethod
    def _active_step(plan: PlanCandidate, time_hours: float) -> PlanStep:
        active = plan.steps[0]
        for step in plan.steps:
            if step.time_hours <= time_hours + 1e-9:
                active = step
        return active

    @staticmethod
    def _inventories_at(stock: dict, time_hours: float) -> dict[str, float]:
        current = stock["timeline"][0]["inventories"]
        for entry in stock["timeline"]:
            if entry["time_hours"] <= time_hours + 1e-9:
                current = entry["inventories"]
        return dict(current)

    @staticmethod
    def _reasons_at(stock: dict, time_hours: float) -> tuple[str, ...]:
        for entry in stock["timeline"]:
            if abs(entry["time_hours"] - time_hours) < 1e-9:
                return tuple(entry["reasons"])
        return ()

    # --- Choosing ---

    def plan(self, confirmed=(), budget: int = 120) -> dict:
        """Build, evaluate and rank plans. Returns the chosen one with its alternatives."""
        plans, info = self.build_plans(budget)
        evaluations = []
        by_id = {}
        for candidate in plans:
            try:
                evaluation = self.evaluate(candidate, confirmed)
            except (PlannerError, ValueError) as exc:
                continue
            evaluations.append(evaluation)
            by_id[candidate.plan_id] = candidate
        min_gain = float(self.scenario.policy.get("min_useful_gain", 0.0))
        result = rank(evaluations, hold_id="hold", min_useful_gain=min_gain)
        chosen_id = result["selected"]["candidate_id"] if result["selected"] else None
        result["selected_plan"] = by_id[chosen_id].to_dict() if chosen_id in by_id else None
        result["search"] = info
        result["confirmed_actions"] = [{"applied_at_hours": at, "controls": dict(controls)}
                                       for at, controls in confirmed]
        result["note"] = ("Выданный план не считается исполненным. Он войдёт в состояние только "
                          "как подтверждённое оператором действие.")
        return result

    def execute(self, command: PlanningCommand) -> PlanningResult:
        """Application entry point for planning an operation."""
        if not isinstance(command, PlanningCommand):
            raise TypeError("PlanOperation.execute expects PlanningCommand")
        return self.plan(confirmed=command.confirmed, budget=command.budget)
