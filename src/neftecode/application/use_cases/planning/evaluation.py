from dataclasses import replace
import math

from neftecode.domain.advisory.entities import PlanStep
from neftecode.domain.advisory.gate import TrajectoryPoint, check_plan
from neftecode.domain.advisory.optimizer import Candidate, Evaluation
from neftecode.domain.production.inventory import InventoryLedger
from neftecode.domain.production.park import AVAILABLE, DRAINING, FILLING, READY
from neftecode.domain.production.park_evaluator import (
    ParkEvaluator,
    ParkFrame,
    ParkStep,
    ParkTrajectory,
    TankOperation,
    initial_park,
)
from neftecode.domain.shared.primitives import QUALITIES, volume_additive_density

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


def _worst_full(details: list, severities: list) -> dict | None:
    known = [(value, index) for index, value in enumerate(severities) if value is not None]
    if not known or not details or max(known)[1] >= len(details):
        return None
    return {**details[max(known)[1]], "step_index": max(known)[1]}


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


class PlanEvaluationMixin:

    def evaluate(self, plan: PlanCandidate, confirmed=(), initial_tanks=None, current_operation=None) -> Evaluation:
        times = [s.time_hours for s in plan.steps]
        if times != sorted(times) or times[0] != 0.0:
            raise PlannerError(f"{plan.plan_id}: шаги плана должны начинаться в 0 ч и возрастать")
        confirmed, deltas = self._plan_moves(plan, confirmed, current_operation)
        ledger = InventoryLedger(self.scenario)
        if initial_tanks is not None:
            ledger.tanks = dict(initial_tanks)
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
        park = self._evaluate_park(plan, grid, inflow_properties, initial_tanks)
        for index, time_hours in enumerate(grid):
            spec = self._active_step(plan, time_hours)
            stream = self.chain.run_at(time_hours, pending)
            properties = stock["timeline"][index]["properties"]
            park_payload = None
            if park is not None:
                frame = park.frames[index]
                park_payload = {**frame.state.to_dict(), "model_version": park.model_version,
                                "reasons": list(frame.reasons)}
                component = self.scenario.tank_park.component_tank_id
                for tank_payload in park_payload["tanks"]:
                    if tank_payload["status"] == FILLING and tank_payload["mass_t"] == 0.0:
                        tank_payload["forecast_properties"] = dict(inflow_properties[time_hours][component])
                properties = {**properties, component: self._park_properties(park, index)}
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
                inventory_reasons=reasons, park=park_payload))
            costs.append(self.economics.step_cost(
                spec.recipe, spec.throughput_tph, self._duration(grid, index),
                spec.additive_dose, trajectory[-1].controls.get("ht_reactor_inlet_temp_c")))
            severity = self.economics.severity(trajectory[-1].controls)
            severities.append(severity["index"] if severity["available"] else None)
            details.append(severity)

        gate = check_plan(plan.plan_id, trajectory, self.scenario, stock["terminal"])
        summary = self.economics.summarise(costs)
        known = [s for s in severities if s is not None]
        applicability = tuple((point.time_hours, point.applicability) for point in trajectory)
        return Evaluation(
            Candidate(plan.plan_id, dict(plan.steps[0].controls), dict(plan.steps[0].recipe),
                      plan.steps[0].throughput_tph, plan.steps[0].additive_dose, plan.changes),
            gate, summary["production_t"], summary["cost_per_tonne"],
            max(known) if known else None,
            _worst_severity(details, severities), _worst_full(details, severities), applicability,
            park.to_dict() if park is not None else None)

    def _evaluate_park(self, plan: PlanCandidate, grid: list[float], inflow_properties: dict,
                       initial_tanks=None):
        config = self.scenario.tank_park
        if config is None:
            return None
        component = config.component_tank_id
        tank = self.scenario.tank(component)
        initial_properties = {name: tank.property_value(name) for name in QUALITIES}
        state = initial_park(config, initial_properties, tank.inflow.value)
        legacy = (initial_tanks or {}).get(component)
        if legacy is not None:
            source = next((item for item in state.tanks if item.status == DRAINING), None)
            if source is not None:
                mass = min(source.capacity_t, legacy.inventory_t)
                replacement = replace(
                    source, mass_t=mass, properties=dict(legacy.properties),
                    status=(DRAINING if mass > 1e-9 else AVAILABLE),
                    batch_id=(source.batch_id if mass > 1e-9 else None),
                    provenance="legacy_single_tank_override")
                state = type(state)(tuple(replacement if item.tank_id == source.tank_id else item
                                          for item in state.tanks))
        frames = [ParkFrame(grid[0], state, 0.0, 0.0)]
        reasons = []
        evaluator = ParkEvaluator()
        for index, time_h in enumerate(grid[:-1]):
            duration = grid[index + 1] - time_h
            spec = self._active_step(plan, time_h)
            left, interval_in, interval_out = duration, 0.0, 0.0
            interval_in_by, interval_out_by, interval_reasons = {}, {}, []
            substep = 0
            while left > 1e-9:
                substep += 1
                if substep > 32:
                    raise PlannerError(f"tank_park: слишком много событий внутри шага {time_h:g} ч")
                operations: dict[str, TankOperation] = {}
                step_reasons = []

                filling = next((item for item in state.tanks if item.status == FILLING), None)
                if filling is None:
                    filling = next((item for item in state.tanks if item.status == AVAILABLE), None)
                if filling is None:
                    step_reasons.append(f"На {time_h + duration - left:g} ч нет резервуара, "
                                        f"доступного для притока {component}")
                else:
                    operations[filling.tank_id] = TankOperation(
                        inflow_tph=tank.inflow.value,
                        inflow_properties=inflow_properties[time_h][component],
                        batch_id=(f"{component}-batch-{index}-{substep}"
                                  if filling.status == AVAILABLE else None))

                demand = spec.throughput_tph * spec.recipe.get(component, 0.0)
                remaining = demand
                sources = [item for item in state.tanks if item.status == DRAINING]
                sources += [item for item in state.tanks if item.status == READY]
                rates = {}
                for source in sources:
                    if remaining <= 1e-9:
                        break
                    rate = min(remaining, source.nominal_drain_tph)
                    rates[source.tank_id] = rate
                    existing = operations.get(source.tank_id, TankOperation())
                    operations[source.tank_id] = TankOperation(
                        inflow_tph=existing.inflow_tph, inflow_properties=existing.inflow_properties,
                        batch_id=existing.batch_id, finish_filling=existing.finish_filling,
                        start_draining=source.status == READY, demand_tph=rate)
                    remaining -= rate
                if remaining > 1e-9:
                    step_reasons.append(
                        f"На {time_h + duration - left:g} ч готовые партии не покрывают спрос "
                        f"{demand:.3f} т/ч: не хватает {remaining:.3f} т/ч")

                event_times = [left]
                if filling is not None and tank.inflow.value > 0:
                    event_times.append(max(0.0, (filling.capacity_t - filling.mass_t) / tank.inflow.value))
                event_times.extend(item.passport_ready_in_h for item in state.tanks
                                   if item.status == "awaiting_passport" and item.passport_ready_in_h is not None)
                event_times.extend(state.tank(tank_id).mass_t / rate for tank_id, rate in rates.items() if rate > 0)
                positive = [value for value in event_times if value > 0.0]
                delta = min(positive) if positive else left
                result = evaluator.evaluate(state, [ParkStep(delta, operations, tuple(step_reasons))])
                frame = result.frames[-1]
                interval_in += frame.inflow_t
                interval_out += frame.outflow_t
                for tank_id, mass in frame.inflow_by_tank.items():
                    interval_in_by[tank_id] = interval_in_by.get(tank_id, 0.0) + mass
                for tank_id, mass in frame.outflow_by_tank.items():
                    interval_out_by[tank_id] = interval_out_by.get(tank_id, 0.0) + mass
                interval_reasons.extend(result.reasons)
                reasons.extend(result.reasons)
                state = result.terminal
                left -= delta
            frames.append(ParkFrame(grid[index + 1], state, interval_in, interval_out,
                                    interval_in_by, interval_out_by,
                                    tuple(dict.fromkeys(interval_reasons))))
        unique = tuple(dict.fromkeys(reasons))
        return ParkTrajectory(tuple(frames), not unique, unique)

    @staticmethod
    def _park_properties(park: ParkTrajectory, index: int) -> dict[str, float | None]:
        state = park.frames[index].state
        weights = (park.frames[index + 1].outflow_by_tank
                   if index + 1 < len(park.frames) else {})
        if not weights:
            weights = {tank.tank_id: 1.0 for tank in state.tanks if tank.status == DRAINING}
        total = sum(weights.values())
        if total <= 0:
            return {name: None for name in QUALITIES}
        result = {}
        for name in QUALITIES:
            values = [(state.tank(tank_id).properties.get(name), weight) for tank_id, weight in weights.items()]
            if any(value is None for value, _ in values):
                result[name] = None
            elif name == "density_kgm3":
                result[name] = volume_additive_density(
                    {tank_id: weight for tank_id, weight in weights.items()},
                    {tank_id: state.tank(tank_id).properties[name] for tank_id in weights},
                )
            else:
                result[name] = sum(value * weight for value, weight in values) / total
        return result

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

    def _plan_moves(self, plan: PlanCandidate, confirmed=(), current_operation=None):
        confirmed = self.confirmed_with_operation(confirmed, current_operation)
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
        return confirmed, deltas

    def action_events(self, plan: PlanCandidate, confirmed=(), current_operation=None) -> list[dict]:
        """Моменты действий плана и объявленного отклика — из тех же сдвигов, что считает evaluate().

        Управляющее воздействие действует на поток после своей стадии через объявленное
        сценарием запаздывание; рецептура, выпуск и присадка в модели смешения действуют со
        своего шага. Уже действующий текущий режим событием не считается.
        """
        _, deltas = self._plan_moves(plan, confirmed, current_operation)
        moves = [("confirmed", at, controls) for at, controls in sorted(confirmed, key=lambda item: item[0])]
        moves += [("plan", at, controls) for at, controls in deltas]
        events = []
        for origin, at, controls in moves:
            for stage_id in ("avt", "hydrotreating"):
                stage = self.scenario.stages[stage_id]
                names = {k: v for k, v in controls.items() if k in stage.controls}
                if not names:
                    continue
                lag = stage.response_lag_hours
                event = {"kind": "control", "origin": origin, "stage": stage_id, "t": at,
                         "controls": names, "response_t": at + lag.value,
                         "lag_hours": lag.value, "lag_source": lag.source}
                model = self.chain.hydrotreating
                if stage_id == "hydrotreating" and model.horizon_response_share < 1:
                    event["partial_response"] = {"share": model.horizon_response_share,
                                                 "until_hours": model.horizon_response_until_hours}
                events.append(event)
        operation = self.scenario.current_operation
        previous = {"recipe": dict(operation.recipe), "throughput_tph": operation.throughput.value,
                    "additive_dose": 0.0}
        if current_operation is not None:
            previous = {"recipe": dict(current_operation["recipe"]),
                        "throughput_tph": current_operation["throughput_tph"],
                        "additive_dose": current_operation.get("additive_dose", 0.0)}
        for step in plan.steps:
            changed = []
            if any(abs(step.recipe.get(k, 0.0) - previous["recipe"].get(k, 0.0)) > 1e-9
                   for k in set(step.recipe) | set(previous["recipe"])):
                changed.append("recipe")
            if abs(step.throughput_tph - previous["throughput_tph"]) > 1e-9:
                changed.append("throughput_tph")
            if abs(step.additive_dose - previous["additive_dose"]) > 1e-9:
                changed.append("additive_dose")
            if changed:
                events.append({"kind": "blend", "origin": "plan", "t": step.time_hours, "changed": changed,
                               "recipe": dict(step.recipe), "throughput_tph": step.throughput_tph,
                               "additive_dose": step.additive_dose, "response_t": step.time_hours,
                               "lag_hours": 0.0, "lag_source": "model_blend_step"})
            previous = {"recipe": dict(step.recipe), "throughput_tph": step.throughput_tph,
                        "additive_dose": step.additive_dose}
        return sorted(events, key=lambda e: (e["t"], e["kind"]))

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
