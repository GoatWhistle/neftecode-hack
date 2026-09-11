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
from dataclasses import dataclass, field
import math

from .blending import Blender
from .economics import Economics
from .gate import TrajectoryStep, check_plan
from .inventory import InventoryLedger
from .optimizer import Candidate, CandidateGenerator, Evaluation, rank
from .process import ChainModel
from .scenario import Scenario


class PlannerError(ValueError):
    """Raised when a plan is structurally impossible to evaluate."""


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


@dataclass(frozen=True)
class PlanStepSpec:
    """One step of a candidate plan."""

    time_hours: float
    controls: dict[str, float]
    recipe: dict[str, float]
    throughput_tph: float
    additive_dose: float = 0.0

    def to_dict(self) -> dict:
        return {"time_hours": self.time_hours, "controls": dict(self.controls),
                "recipe": dict(self.recipe), "throughput_tph": self.throughput_tph,
                "additive_dose": self.additive_dose}


@dataclass(frozen=True)
class PlanCandidate:
    """A sequence of steps, plus how many of them actually change anything."""

    plan_id: str
    steps: tuple[PlanStepSpec, ...]
    changes: int = 0
    intent: str = ""

    def immediate(self) -> PlanStepSpec:
        return self.steps[0]

    def to_dict(self) -> dict:
        return {"plan_id": self.plan_id, "intent": self.intent, "changes": self.changes,
                "steps": [s.to_dict() for s in self.steps]}


@dataclass
class Planner:
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

    def build_plans(self, budget: int = 120) -> tuple[list[PlanCandidate], dict]:
        """Single-step plans plus transitional two-phase plans, in a fixed order."""
        generator = CandidateGenerator(self.scenario, budget=budget)
        singles, info = generator.generate()
        base = self.base_controls()
        plans: list[PlanCandidate] = []
        for candidate in singles:
            plans.append(PlanCandidate(
                candidate.candidate_id,
                (PlanStepSpec(0.0, dict(candidate.controls), dict(candidate.recipe),
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
                            (PlanStepSpec(0.0, dict(correction.controls),
                                          self._recipe_with_reserve(relief), throughput, 0.0),
                             PlanStepSpec(switch, dict(correction.controls),
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

    def evaluate(self, plan: PlanCandidate, confirmed=()) -> Evaluation:
        """Run the plan through the chain, the blender, the tanks and the gate.

        `confirmed` carries operator-confirmed actions as `(applied_at_hours, controls)`. The
        plan's own steps are treated as proposals: they shape the trajectory being evaluated,
        but they never enter `confirmed` on their own.
        """
        times = [s.time_hours for s in plan.steps]
        if times != sorted(times) or times[0] != 0.0:
            raise PlannerError(f"{plan.plan_id}: шаги плана должны начинаться в 0 ч и возрастать")
        ledger = InventoryLedger(self.scenario)
        ledger_steps = [(s.time_hours, s.recipe, s.throughput_tph) for s in plan.steps]
        stock = ledger.run_plan(ledger_steps)
        # A plan step carries its DELTA from the scenario baseline, not a full set of setpoints.
        # Otherwise a plan that does not touch a control would silently revert a correction the
        # operator has already confirmed.
        baseline = self.base_controls()
        deltas = tuple((step.time_hours,
                        {k: v for k, v in step.controls.items() if abs(v - baseline[k]) > 1e-9})
                       for step in plan.steps)
        pending = tuple(confirmed) + tuple((t, d) for t, d in deltas if d)

        trajectory: list[TrajectoryStep] = []
        costs = []
        severities = []
        grid = self.grid()
        inventories_at = {entry["time_hours"]: entry["inventories"] for entry in stock["timeline"]}
        for index, time_hours in enumerate(grid):
            spec = self._active_step(plan, time_hours)
            stream = self.chain.run_at(time_hours, pending)
            blend = self.blender.blend(spec.recipe, spec.throughput_tph,
                                       hours=self._duration(grid, index),
                                       additive_dose=spec.additive_dose)
            # The hydrotreated stream feeds the main tank, so its sulfur enters the blend
            # through that component rather than replacing the blend result.
            qualities = dict(blend.qualities)
            if stream.sulfur_mgkg is not None and qualities.get("sulfur_mgkg") is not None:
                main_share = spec.recipe.get(self._main_id(), 0.0)
                qualities["sulfur_mgkg"] = (qualities["sulfur_mgkg"]
                                            - main_share * self._main_sulfur()
                                            + main_share * stream.sulfur_mgkg)
            elif stream.sulfur_mgkg is None:
                qualities["sulfur_mgkg"] = None
            inventories = self._inventories_at(stock, time_hours)
            reasons = self._reasons_at(stock, time_hours)
            trajectory.append(TrajectoryStep(
                time_hours, qualities, self._effective_controls(time_hours, pending),
                inventories, spec.recipe, spec.throughput_tph, spec.additive_dose,
                stream.applicability, reasons))
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

    def _main_id(self) -> str:
        return self.scenario.available_tanks()[0].tank_id

    def _main_sulfur(self) -> float:
        return self.scenario.tank(self._main_id()).property_value("sulfur_mgkg")

    def _avt_controls(self, spec: PlanStepSpec) -> dict[str, float]:
        names = set(self.scenario.stages["avt"].controls)
        return {k: v for k, v in spec.controls.items() if k in names}

    @staticmethod
    def _duration(grid, index) -> float:
        return grid[index + 1] - grid[index] if index + 1 < len(grid) else 0.0

    @staticmethod
    def _active_step(plan: PlanCandidate, time_hours: float) -> PlanStepSpec:
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
