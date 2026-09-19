from collections.abc import Callable
from dataclasses import dataclass
import copy

from neftecode.application.use_cases.make_decision import MakeDecision
from neftecode.application.use_cases.plan_operation import PlanOperation, PlanCandidate, PlanStep
from neftecode.domain.advisory.optimizer import DEFAULT_BUDGET
from neftecode.domain.production.scenario import Scenario
from neftecode.evaluation.robustness import RobustnessCheck
from neftecode.evaluation.tank_estimate import default_tank_estimate_factory


HOLD = "hold"
THRESHOLD = "threshold"
ADVISOR = "advisor"
ADVISOR_NO_TRANSITION = "advisor_without_transition"
ADVISOR_NO_TERMINAL = "advisor_without_terminal_rule"
STRATEGIES = (HOLD, THRESHOLD, ADVISOR, ADVISOR_NO_TRANSITION, ADVISOR_NO_TERMINAL)


class BenchmarkError(ValueError):
    pass


def _outcome(evaluation, plan, scenario: Scenario) -> dict:
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

    scenario: Scenario
    raw: dict
    budget: int = DEFAULT_BUDGET
    scenario_parser: Callable[[dict], Scenario] | None = None

    def hold_plan(self) -> PlanCandidate:
        planner = PlanOperation(self.scenario)
        operation = self.scenario.current_operation
        recipe = {t.tank_id: float(operation.recipe.get(t.tank_id, 0.0)) for t in self.scenario.tanks}
        return PlanCandidate(HOLD, (PlanStep(0.0, planner.base_controls(), recipe,
                                                 operation.throughput.value),), 0,
                             "сохранение режима без изменений")

    def threshold_plan(self) -> PlanCandidate:
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
        if self.scenario_parser is None:
            raise BenchmarkError("Для benchmark не передан парсер сценария")
        scenario = self.scenario_parser(raw)
        orchestrator = MakeDecision(
            scenario,
            robustness_evaluator=RobustnessCheck(
                scenario, raw, scenario_parser=self.scenario_parser
            ),
            scenario_parser=self.scenario_parser,
            tank_estimate_factory=default_tank_estimate_factory,
        )
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
            results[name] = {**_outcome(evaluation, plan, self.scenario_parser(raw)),
                             "status": decision["status"],
                             "plan_id": plan.plan_id, "intent": plan.intent}
        return {"scenario_id": self.scenario.scenario_id, "strategies": results}
