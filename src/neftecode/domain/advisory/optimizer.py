from dataclasses import dataclass
import math

from neftecode.domain.advisory.entities import GateResult
from neftecode.domain.production.scenario import Scenario

RANKING = ("-production_t", "cost_per_tonne", "severity_index", "changes", "candidate_id")

DEFAULT_BUDGET = 1200


class OptimizerError(ValueError):
    pass


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


@dataclass(frozen=True)
class Candidate:

    candidate_id: str
    controls: dict[str, float]
    recipe: dict[str, float]
    throughput_tph: float
    additive_dose: float = 0.0
    changes: int = 0

    def to_dict(self) -> dict:
        return {"candidate_id": self.candidate_id, "controls": dict(self.controls),
                "recipe": dict(self.recipe), "throughput_tph": self.throughput_tph,
                "additive_dose": self.additive_dose, "changes": self.changes}


def _fractions(step: float = 0.05) -> list[float]:
    count = int(round(1.0 / step))
    return [round(i * step, 6) for i in range(count + 1)]


@dataclass
class CandidateGenerator:

    scenario: Scenario
    fraction_step: float = 0.05
    throughput_step_tph: float = 10.0
    budget: int = DEFAULT_BUDGET

    def current(self) -> Candidate:
        controls = {}
        for stage in self.scenario.stages.values():
            for name, spec in stage.controls.items():
                controls[name] = spec["current"].value
        tanks = self.scenario.available_tanks()
        if not tanks:
            raise OptimizerError("Нет доступных резервуаров: смешивать нечего")
        operation = self.scenario.current_operation
        recipe = {t.tank_id: float(operation.recipe.get(t.tank_id, 0.0)) for t in self.scenario.tanks}
        return Candidate("hold", controls, recipe, operation.throughput.value, 0.0, changes=0)

    def _throughputs(self) -> list[float]:
        current = self.scenario.current_operation.throughput.value
        floor = current * float(self.scenario.policy.get("min_throughput_fraction", 0.5))
        values = []
        value = current
        while value >= floor - 1e-9:
            values.append(round(value, 6))
            value -= self.throughput_step_tph
        return sorted(values) or [current]

    def _control_options(self) -> list[dict[str, float]]:
        base = {}
        moves = []
        for stage in self.scenario.stages.values():
            for name, spec in sorted(stage.controls.items()):
                base[name] = spec["current"].value
        for stage in self.scenario.stages.values():
            for name, spec in sorted(stage.controls.items()):
                step = spec["step"].value if spec.get("step") else 0.0
                low, high = spec["min"].value, spec["max"].value
                if step <= 0:
                    continue
                for delta in (-step, step):
                    target = round(base[name] + delta, 6)
                    if low - 1e-9 <= target <= high + 1e-9:
                        moves.append({**base, name: target})
        return [dict(base)] + moves

    def generate(self, allow_control_moves: bool = True,
                 forbidden: tuple[str, ...] = ()) -> tuple[list[Candidate], dict]:
        tanks = [t.tank_id for t in self.scenario.available_tanks()]
        if not tanks:
            raise OptimizerError("Нет доступных резервуаров: смешивать нечего")
        base_controls = self.current().controls
        doses = [0.0]
        if self.scenario.additive is not None:
            top = self.scenario.additive.max_dose_fraction.value
            doses = sorted({0.0, round(top / 2, 6), round(top, 6)})
        recipes = [r for r in (self._recipe(tanks, f) for f in _fractions(self.fraction_step))
                   if r is not None]
        throughputs = self._throughputs()
        base_throughput = self.scenario.current_operation.throughput.value
        control_sets = self._control_options() if allow_control_moves else [dict(base_controls)]

        layers = [
            ("recipe_and_throughput",
             [(r, q, dict(base_controls), 0.0) for r in recipes for q in throughputs]),
            ("control_moves",
             [(r, base_throughput, c, 0.0) for r in recipes for c in control_sets[1:]]),
            ("additive",
             [(r, base_throughput, dict(base_controls), d)
              for r in recipes for d in doses if d > 0]),
        ]
        hold = self.current()
        candidates: list[Candidate] = [hold]
        next_index = 1
        seen = {self._signature(hold)}
        exhausted, covered = False, []
        for name, combinations in layers:
            added = 0
            for recipe, throughput, controls, dose in combinations:
                if len(candidates) >= self.budget:
                    exhausted = True
                    break
                changes = sum(1 for key, value in controls.items()
                              if abs(value - base_controls[key]) > 1e-9)
                changes += 0 if dose == 0 else 1
                changes += 0 if self._same_recipe(recipe, hold.recipe) else 1
                changes += 0 if abs(throughput - hold.throughput_tph) < 1e-9 else 1
                candidate = Candidate(f"c{next_index:04d}", dict(controls), recipe,
                                      throughput, dose, changes)
                signature = self._signature(candidate)
                if signature in seen:
                    continue
                next_index += 1
                if candidate.candidate_id in forbidden:
                    seen.add(signature)
                    continue
                seen.add(signature)
                candidates.append(candidate)
                added += 1
            covered.append({"layer": name, "added": added, "complete": not exhausted})
            if exhausted:
                break
        info = {"generated": len(candidates), "budget": self.budget, "budget_exhausted": exhausted,
                "layers": covered,
                "fraction_step": self.fraction_step, "throughput_step_tph": self.throughput_step_tph,
                "claim": "Перебор ограничен бюджетом и шагом сетки. Глобальная оптимальность "
                         "не заявляется: результат — лучший из рассмотренных вариантов."}
        return candidates, info

    @staticmethod
    def _same_recipe(a: dict, b: dict) -> bool:
        keys = set(a) | set(b)
        return all(abs(a.get(k, 0.0) - b.get(k, 0.0)) < 1e-9 for k in keys)

    @staticmethod
    def _signature(candidate: Candidate) -> tuple:
        return (tuple(sorted(candidate.recipe.items())), candidate.throughput_tph,
                tuple(sorted(candidate.controls.items())), candidate.additive_dose)

    def _recipe(self, tanks: list[str], reserve_fraction: float) -> dict[str, float] | None:
        if len(tanks) == 1:
            return {tanks[0]: 1.0} if reserve_fraction == 0.0 else None
        main, reserve = tanks[0], tanks[1]
        return {main: round(1.0 - reserve_fraction, 6), reserve: reserve_fraction,
                **{t: 0.0 for t in tanks[2:]}}


@dataclass
class Evaluation:

    candidate: Candidate
    gate: GateResult
    production_t: float = 0.0
    cost_per_tonne: float | None = None
    severity_index: float | None = None
    severity_detail: dict | None = None

    @property
    def feasible(self) -> bool:
        return self.gate.feasible

    def key(self) -> tuple:
        return (-self.production_t,
                self.cost_per_tonne if _finite(self.cost_per_tonne) else math.inf,
                self.severity_index if _finite(self.severity_index) else math.inf,
                self.candidate.changes,
                self.candidate.candidate_id)

    def to_dict(self) -> dict:
        return {**self.candidate.to_dict(), "feasible": self.feasible,
                "production_t": self.production_t, "cost_per_tonne": self.cost_per_tonne,
                "severity_index": self.severity_index,
                "rejection_reasons": list(self.gate.rejection_reasons())}


def rank(evaluations, hold_id: str = "hold", min_useful_gain: float = 0.0) -> dict:
    feasible = [e for e in evaluations if e.feasible]
    rejected = [e for e in evaluations if not e.feasible]
    if not feasible:
        return {"selected": None, "alternatives": [], "rejected": [e.to_dict() for e in rejected],
                "reason": "Ни один вариант не прошёл обязательные проверки"}
    ordered = sorted(feasible, key=lambda e: e.key())
    best = ordered[0]
    hold = next((e for e in feasible if e.candidate.candidate_id == hold_id), None)
    reason = "Лучший из допустимых по правилу: выпуск, затем стоимость, затем тяжесть режима"
    if hold is not None and best.candidate.candidate_id != hold_id:
        same_production = best.production_t <= hold.production_t + 1e-9
        hold_cost = hold.cost_per_tonne
        gain = 0.0
        if _finite(hold_cost) and hold_cost > 0 and _finite(best.cost_per_tonne):
            gain = (hold_cost - best.cost_per_tonne) / hold_cost
        if same_production and gain < min_useful_gain:
            best = hold
            reason = (f"Выигрыш изменения {gain:.2%} меньше минимального полезного "
                      f"{min_useful_gain:.0%} при том же выпуске: режим сохраняется")
    return {
        "selected": best.to_dict(),
        "alternatives": [e.to_dict() for e in ordered if e is not best][:5],
        "rejected": [e.to_dict() for e in rejected][:20],
        "ranking": list(RANKING),
        "reason": reason,
        "claim": "Сравниваются только варианты, прошедшие обязательные проверки. "
                 "Недопустимый вариант не может выиграть никакими весами.",
    }
