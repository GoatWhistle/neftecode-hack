from dataclasses import replace
import math

from neftecode.domain.advisory.entities import PlanStep
from neftecode.domain.advisory.gate import TrajectoryPoint, check_plan
from neftecode.domain.advisory.optimizer import Candidate, Evaluation
from neftecode.domain.production.inventory import InventoryLedger

from .candidate import PlanCandidate, PlannerError


def _worst_severity(details: list, severities: list) -> dict | None:
    known = [(value, index) for index, value in enumerate(severities) if value is not None]
    if not known or not details:
        return None
    position = max(known)[1]
    if position >= len(details):
        return None
    worst = details[position]
    return {"index": worst.get("index"), "terms": dict(worst.get("terms") or {}),
            "weights": dict(worst.get("weights") or {}),
            "reference_temp_c": worst.get("reference_temp_c"),
            "reference_flow_m3h": worst.get("reference_flow_m3h"),
            "control_range_c": worst.get("control_range_c"),
            "step_index": position, "reason": worst.get("reason"), "scope": worst.get("scope")}


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


class PlanEvaluationMixin:

    def evaluate(self, plan: PlanCandidate, confirmed=(), initial_tanks=None, current_operation=None) -> Evaluation:
        times = [s.time_hours for s in plan.steps]
        if times != sorted(times) or times[0] != 0.0:
            raise PlannerError(f"{plan.plan_id}: шаги плана должны начинаться в 0 ч и возрастать")
        confirmed = self.confirmed_with_operation(confirmed, current_operation)
        ledger = InventoryLedger(self.scenario)
        if initial_tanks is not None:
            ledger.tanks = dict(initial_tanks)
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
        details = []
        grid = self.grid()
        ledger_steps = [(t, self._active_step(plan, t).recipe,
                         self._active_step(plan, t).throughput_tph) for t in grid]
        inflow_properties = {}
        for t in grid:
            inflow_properties[t] = self.inflow_properties(t, pending)
        stock = ledger.run_plan(ledger_steps, inflow_properties)
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
            details.append(severity)

        gate = check_plan(plan.plan_id, trajectory, self.scenario, stock["terminal"])
        summary = self.economics.summarise(costs)
        known = [s for s in severities if s is not None]
        return Evaluation(
            Candidate(plan.plan_id, dict(plan.steps[0].controls), dict(plan.steps[0].recipe),
                      plan.steps[0].throughput_tph, plan.steps[0].additive_dose, plan.changes),
            gate, summary["production_t"], summary["cost_per_tonne"],
            max(known) if known else None,
            _worst_severity(details, severities))

    def lookahead(self, plan: PlanCandidate, hours: float, confirmed=(), initial_tanks=None,
                  current_operation=None) -> dict:
        if not _finite(hours) or hours <= 0:
            raise PlannerError("lookahead: длительность должна быть положительной")
        base = self.scenario.horizon.hours
        extended = replace(self.scenario, horizon=replace(self.scenario.horizon, hours=base + hours))
        evaluation = type(self)(extended).evaluate(plan, confirmed, initial_tanks=initial_tanks,
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
