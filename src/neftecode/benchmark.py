"""Is the advisor worth more than a simple rule? Measured on identical conditions.

Three strategies are run on exactly the same scenarios, with the same limits, the same tanks
and the same models:

* **hold** — keep the current regime whatever happens;
* **threshold** — a single rule: if the predicted sulfur is above the limit, raise the reserve
  fraction one notch at a time until it fits. It gets the same hard checks as everyone else,
  because building a deliberately crippled opponent would prove nothing;
* **advisor** — the full agent loop.

Two ablations answer "what are the extra parts for": the advisor without transitional planning
(single-step plans only) and the advisor without the terminal stock rule.

What the result is NOT: measured savings at a refinery. Every number here comes from our own
scenario models, and the advisor is compared inside the same model it optimises against. That
limitation is reported with the numbers, not left to the reader.
"""
from dataclasses import dataclass
import copy
import json

from neftecode.domain.advisory.gate import check_plan
from neftecode.domain.advisory.optimizer import Candidate, Evaluation
from neftecode.application.use_cases.make_decision import MakeDecision
from neftecode.application.use_cases.plan_operation import PlanOperation, PlanCandidate, PlanStep
from neftecode.scenario import Scenario, parse_scenario

HOLD = "hold"
THRESHOLD = "threshold"
ADVISOR = "advisor"
ADVISOR_NO_TRANSITION = "advisor_without_transition"
ADVISOR_NO_TERMINAL = "advisor_without_terminal_rule"
STRATEGIES = (HOLD, THRESHOLD, ADVISOR, ADVISOR_NO_TRANSITION, ADVISOR_NO_TERMINAL)


class BenchmarkError(ValueError):
    """Raised when strategies would not be compared on identical conditions."""


def _outcome(evaluation, plan, scenario: Scenario) -> dict:
    """Figures for one strategy, including the ones the advisor does NOT optimise.

    Masses are integrated over the horizon: each step is held until the next one, and the last
    until the horizon ends. Summing per-step rates without their durations would make a
    two-phase plan look twice as wasteful as a constant one.
    """
    tanks = [t.tank_id for t in scenario.available_tanks()]
    reserve_id = tanks[1] if len(tanks) > 1 else tanks[0]
    times = [s.time_hours for s in plan.steps] + [scenario.horizon.hours]
    reserve_used = 0.0
    additive_used = 0.0
    for index, step in enumerate(plan.steps):
        hours = max(0.0, times[index + 1] - times[index])
        reserve_used += step.throughput_tph * step.recipe.get(reserve_id, 0.0) * hours
        additive_used += step.throughput_tph * step.additive_dose * hours
    violations = [c for c in evaluation.gate.checks if c.status == "fail"]
    unknown = [c for c in evaluation.gate.checks if c.status == "unknown"]
    return {
        "feasible": evaluation.feasible,
        "violations": len(violations),
        "violation_hours": sorted({c.time_hours for c in violations if c.time_hours is not None}),
        "unknown_requirements": len(unknown),
        "production_t": evaluation.production_t,
        "cost_per_tonne": evaluation.cost_per_tonne,
        "severity_index": evaluation.severity_index,
        "changes": plan.changes,
        "reserve_used_t": reserve_used,
        "additive_used_t": additive_used,
    }


@dataclass
class Benchmark:
    """Runs every strategy on the same scenario and reports wins, losses and refusals."""

    scenario: Scenario
    raw: dict
    budget: int = 400

    def hold_plan(self) -> PlanCandidate:
        planner = PlanOperation(self.scenario)
        operation = self.scenario.current_operation
        recipe = {t.tank_id: float(operation.recipe.get(t.tank_id, 0.0)) for t in self.scenario.tanks}
        return PlanCandidate(HOLD, (PlanStep(0.0, planner.base_controls(), recipe,
                                                 operation.throughput.value),), 0,
                             "сохранение режима без изменений")

    def threshold_plan(self) -> PlanCandidate:
        """The simple rule, given the same limits and the same search over reserve fractions.

        It raises the reserve one notch at a time and stops at the first recipe whose blend
        passes: no planning over time, no stock horizon, no cost comparison.
        """
        planner = PlanOperation(self.scenario)
        operation = self.scenario.current_operation
        tanks = [t.tank_id for t in self.scenario.available_tanks()]
        step = 0.05
        for i in range(int(1 / step) + 1):
            fraction = round(i * step, 6)
            recipe = ({tanks[0]: 1.0} if len(tanks) == 1 else
                      {tanks[0]: round(1.0 - fraction, 6), tanks[1]: fraction,
                       **{t: 0.0 for t in tanks[2:]}})
            plan = PlanCandidate(f"{THRESHOLD}_{i:02d}",
                                 (PlanStep(0.0, planner.base_controls(), recipe,
                                               operation.throughput.value),),
                                 int(any(abs(recipe.get(k, 0.0) - operation.recipe.get(k, 0.0)) > 1e-9
                                         for k in set(recipe) | set(operation.recipe))),
                                 "простое пороговое правило по сере")
            try:
                evaluation = planner.evaluate(plan)
            except ValueError:
                continue
            if evaluation.feasible:
                return plan
        return plan

    def _advisor(self, raw: dict, transition: bool = True) -> tuple:
        scenario = parse_scenario(raw)
        from .robustness import RobustnessCheck
        orchestrator = MakeDecision(scenario, robustness_evaluator=RobustnessCheck(scenario, raw))
        if not transition:
            planner = orchestrator.planner
            original = planner.build_plans

            def singles_only(budget):
                plans, info = original(budget)
                kept = [p for p in plans if len(p.steps) == 1]
                info = dict(info, plans=len(kept), ablation="без переходных планов")
                return kept, info

            planner.build_plans = singles_only
        decision = orchestrator.decide(budget=self.budget)
        if decision["selected_plan"] is None:
            return None, None, decision
        selected = decision["selected_plan"]
        plan = PlanCandidate(selected["plan_id"],
                             tuple(PlanStep(**step) for step in selected["steps"]),
                             selected["changes"], selected.get("intent", ""))
        return plan, PlanOperation(scenario).evaluate(plan), decision

    def run(self) -> dict:
        planner = PlanOperation(self.scenario)
        results: dict[str, dict] = {}

        for name, plan in ((HOLD, self.hold_plan()), (THRESHOLD, self.threshold_plan())):
            try:
                evaluation = planner.evaluate(plan)
            except ValueError as exc:
                results[name] = {"refused": True, "reason": str(exc)}
                continue
            results[name] = _outcome(evaluation, plan, self.scenario)

        for name, transition, terminal in ((ADVISOR, True, True),
                                           (ADVISOR_NO_TRANSITION, False, True),
                                           (ADVISOR_NO_TERMINAL, True, False)):
            raw = copy.deepcopy(self.raw)
            if not terminal:
                raw["policy"]["terminal_inventory_rule"] = "none"
            plan, evaluation, decision = self._advisor(raw, transition)
            if plan is None:
                results[name] = {"refused": True, "reason": decision["reason"],
                                 "status": decision["status"]}
                continue
            # The ablation may have changed the policy, so measure against ITS scenario.
            results[name] = {**_outcome(evaluation, plan, parse_scenario(raw)),
                             "status": decision["status"],
                             "plan_id": plan.plan_id, "intent": plan.intent}
        return {"scenario_id": self.scenario.scenario_id, "strategies": results}


def compare(scenarios: list[tuple[Scenario, dict]], budget: int = 400) -> dict:
    """Run every strategy on every scenario and aggregate without dropping the bad cases."""
    per_scenario = [Benchmark(scenario, raw, budget).run() for scenario, raw in scenarios]
    totals: dict[str, dict] = {name: {"feasible": 0, "refused": 0, "violations": 0,
                                      "production_t": 0.0, "scenarios": 0}
                               for name in STRATEGIES}
    for record in per_scenario:
        for name, result in record["strategies"].items():
            bucket = totals[name]
            bucket["scenarios"] += 1
            if result.get("refused"):
                bucket["refused"] += 1
                continue
            bucket["feasible"] += 1 if result["feasible"] else 0
            bucket["violations"] += result["violations"]
            bucket["production_t"] += result["production_t"] if result["feasible"] else 0.0
    wins, losses = _wins_and_losses(per_scenario)
    return {
        "ablations": _ablations(per_scenario),
        "scenarios": per_scenario,
        "totals": totals,
        "wins": wins,
        "losses": losses,
        "aggregation": "Все сценарии входят в итог. Исключать неудачные случаи ради среднего нельзя.",
        "limits": [
            "Числа получены в нашей сценарной модели и не являются экономией реального завода.",
            "Советчик сравнивается внутри той же модели, против которой он оптимизирует; "
            "проверка на структурно иной среде этим экспериментом не сделана.",
            "Пороговое правило получает те же жёсткие проверки и тот же перебор долей резерва: "
            "заведомо слабый соперник не строился.",
            "Набор сценариев мал и выбран нами; это не оценка на новых условиях.",
            "Выпуск стоит первым в правиле выбора: преимущество этой метрики заложено почти по построению, "
            "но при ограниченном бюджете поиска выигрыш не гарантируется. Поэтому отдельно сравниваются "
            "стоимость на тонну, расход резерва и число "
            "изменений режима. Проигрыши по ним перечислены наравне с выигрышами.",
        ],
    }


def _ablations(per_scenario) -> list[dict]:
    """What each switched-off part actually bought, including when removing it looks better."""
    out = []
    for record in per_scenario:
        strategies = record["strategies"]
        full = strategies.get(ADVISOR, {})
        if full.get("refused"):
            continue
        for name, what in ((ADVISOR_NO_TRANSITION, "план во времени"),
                           (ADVISOR_NO_TERMINAL, "правило остатка на конце горизонта")):
            other = strategies.get(name, {})
            if other.get("refused"):
                out.append({"scenario_id": record["scenario_id"], "ablation": what,
                            "effect": "без этой части допустимого плана не находится"})
                continue
            delta = full["production_t"] - other["production_t"]
            if abs(delta) < 1e-9:
                effect = "выпуск не изменился"
            elif delta > 0:
                effect = f"эта часть добавляет {delta:.0f} т выпуска"
            else:
                effect = (f"без этой части выпуск на {-delta:.0f} т выше: ограничение стоит выпуска, "
                          f"и это его цена, а не недостаток")
            out.append({"scenario_id": record["scenario_id"], "ablation": what,
                        "production_with": full["production_t"],
                        "production_without": other["production_t"], "effect": effect})
    return out


#: Dimensions the comparison reports. Only the first is what the advisor ranks by, so the
#: others are where a loss can actually show up.
DIMENSIONS = (
    ("production_t", "выпуск", "больше"),
    ("cost_per_tonne", "стоимость на тонну", "меньше"),
    ("reserve_used_t", "расход резерва", "меньше"),
    ("changes", "число изменений режима", "меньше"),
)


def _better(name: str, a: float, b: float) -> bool:
    """Is `a` better than `b` on this dimension?"""
    direction = next(d for key, _, d in DIMENSIONS if key == name)
    return a > b + 1e-9 if direction == "больше" else a < b - 1e-9


def _wins_and_losses(per_scenario) -> tuple[list, list]:
    """Where the advisor beats the simple strategies, and where it does not.

    Comparison runs over several dimensions on purpose. Production alone is the dimension the
    advisor ranks by while searching a superset of the simple rules' options, so it wins there
    almost by construction; a report showing only that would be a rigged scoreboard.
    """
    wins, losses = [], []
    for record in per_scenario:
        strategies = record["strategies"]
        advisor = strategies.get(ADVISOR, {})
        if advisor.get("refused"):
            simple_ok = [n for n in (HOLD, THRESHOLD)
                         if not strategies[n].get("refused") and strategies[n]["feasible"]]
            (losses if simple_ok else wins).append({
                "scenario_id": record["scenario_id"],
                "note": ("Советчик отказался там, где простое правило нашло допустимый вариант"
                         if simple_ok else
                         "Допустимого варианта нет ни у кого; отказ — правильный ответ")})
            continue
        for name in (HOLD, THRESHOLD):
            other = strategies[name]
            if other.get("refused"):
                wins.append({"scenario_id": record["scenario_id"], "beats": name,
                             "dimension": "выполнимость", "note": "соперник не дал варианта"})
                continue
            if not other["feasible"] and advisor["feasible"]:
                wins.append({"scenario_id": record["scenario_id"], "beats": name,
                             "dimension": "соблюдение ограничений",
                             "note": f"{name} нарушает ограничения в {other['violations']} проверках"})
                continue
            if other["feasible"] and not advisor["feasible"]:
                losses.append({"scenario_id": record["scenario_id"], "loses_to": name,
                               "dimension": "соблюдение ограничений"})
                continue
            if not other["feasible"]:
                continue
            # Both feasible: compare on every declared dimension.
            for key, label, direction in DIMENSIONS:
                mine, theirs = advisor.get(key), other.get(key)
                if mine is None or theirs is None:
                    continue
                if _better(key, mine, theirs):
                    wins.append({"scenario_id": record["scenario_id"], "beats": name,
                                 "dimension": label, "advisor": mine, "other": theirs})
                elif _better(key, theirs, mine):
                    losses.append({"scenario_id": record["scenario_id"], "loses_to": name,
                                   "dimension": label, "advisor": mine, "other": theirs,
                                   "note": f"{label}: у советчика {mine:g}, у {name} {theirs:g} "
                                           f"(лучше {direction})"})
    return wins, losses
