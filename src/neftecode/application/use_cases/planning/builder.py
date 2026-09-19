from dataclasses import replace

from neftecode.domain.advisory.entities import PlanStep
from neftecode.domain.advisory.optimizer import CandidateGenerator

from .candidate import PlanCandidate


class PlanBuilderMixin:

    def build_plans(self, budget: int = 120, current_operation: dict | None = None) -> tuple[list[PlanCandidate], dict]:
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
            steps = self._phased_steps(dict(candidate.controls), dict(candidate.recipe),
                                       candidate.throughput_tph, candidate.additive_dose)
            plans.append(PlanCandidate(
                candidate.candidate_id, steps,
                candidate.changes + (1 if len(steps) > 1 else 0),
                self._phasing_intent(steps)))

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
                        head = self._phased_steps(dict(correction.controls),
                                                  self._recipe_with_reserve(relief), throughput, 0.0,
                                                  until=switch)
                        tail = self._phased_steps(dict(correction.controls),
                                                  self._recipe_with_reserve(max(0.0, relief - relief_step)),
                                                  throughput, 0.0, start=switch)
                        steps = tuple(s for s in head if s.time_hours < switch - 1e-9) + tail
                        plans.append(PlanCandidate(
                            f"t{len(plans):04d}", steps,
                            correction.changes + 1,
                            f"временная помощь смешением до эффекта коррекции через {switch:g} ч"))
        info["plans"] = len(plans)
        return plans, info

    @staticmethod
    def _distinct_corrections(candidates, base: dict[str, float]):
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

    def _on_demand_delays(self) -> dict[str, float]:
        return {t.tank_id: t.production_lead_time_hours for t in self.scenario.tanks
                if t.on_demand and t.production_lead_time_hours > 0}

    @staticmethod
    def _without(recipe: dict[str, float], held: tuple[str, ...]) -> dict[str, float] | None:
        kept = {k: v for k, v in recipe.items() if k not in held}
        total = sum(kept.values())
        if total <= 1e-9:
            return None
        return {k: (round(v / total, 6) if k in kept else 0.0) for k, v in recipe.items()}

    def _phased_steps(self, controls: dict[str, float], recipe: dict[str, float],
                      throughput_tph: float, additive_dose: float,
                      start: float = 0.0, until: float | None = None) -> tuple[PlanStep, ...]:
        horizon = self.scenario.horizon.hours if until is None else until
        delays = self._on_demand_delays()
        delayed = tuple(sorted(k for k, lead in delays.items()
                               if recipe.get(k, 0.0) > 1e-12 and start + lead < horizon - 1e-9))
        blocked = tuple(sorted(k for k, lead in delays.items()
                               if recipe.get(k, 0.0) > 1e-12 and start + lead >= horizon - 1e-9))
        target = dict(recipe)
        if blocked:
            reduced = self._without(target, blocked)
            if reduced is None:
                return (PlanStep(start, controls, target, throughput_tph, additive_dose),)
            target = reduced
            delayed = tuple(k for k in delayed if target.get(k, 0.0) > 1e-12)
        if not delayed:
            return (PlanStep(start, controls, target, throughput_tph, additive_dose),)
        ready = start + max(delays[k] for k in delayed)
        capped = dict(target)
        for tank_id in delayed:
            tank = self.scenario.tank(tank_id)
            room = tank.production_rate_tph * (horizon - start - delays[tank_id])
            share = capped[tank_id] * throughput_tph * (horizon - ready)
            if share > room + 1e-9 and throughput_tph > 0 and horizon - ready > 1e-9:
                capped[tank_id] = round(room / (throughput_tph * (horizon - ready)), 6)
        if capped != target:
            rest = self._without(capped, delayed)
            if rest is None:
                return (PlanStep(start, controls, target, throughput_tph, additive_dose),)
            spare = 1.0 - sum(capped[k] for k in delayed)
            target = {k: (capped[k] if k in delayed else round(rest[k] * spare, 6)) for k in capped}
            target = self._normalised(target)
        head = self._without(target, delayed)
        if head is None:
            return (PlanStep(start, controls, target, throughput_tph, additive_dose),)
        return (PlanStep(start, controls, head, throughput_tph, additive_dose),
                PlanStep(ready, controls, target, throughput_tph, additive_dose))

    @staticmethod
    def _normalised(recipe: dict[str, float]) -> dict[str, float]:
        total = sum(recipe.values())
        if abs(total - 1.0) <= 1e-9 or total <= 1e-9:
            return recipe
        first = max(recipe, key=lambda k: recipe[k])
        out = dict(recipe)
        out[first] = round(out[first] + (1.0 - total), 6)
        return out

    @staticmethod
    def _phasing_intent(steps: tuple[PlanStep, ...]) -> str:
        if len(steps) == 1:
            return "постоянный режим на весь горизонт"
        return (f"компонент по необходимости подключается с {steps[1].time_hours:g} ч, "
                f"когда его успевают наработать")
