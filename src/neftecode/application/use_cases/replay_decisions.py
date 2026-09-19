from dataclasses import dataclass, field, replace
from datetime import datetime
import math

from neftecode.domain.advisory.optimizer import DEFAULT_BUDGET
from neftecode.domain.shared.actions import PendingAction
from neftecode.domain.production.inventory import draw_step
from .execution_state import ExecutionState, HISTORICAL, MODES, ReplayError, SIMULATED, versions
from .make_decision import MakeDecision
from neftecode.domain.production.scenario import Scenario
from neftecode.application.contracts import ReplayCommand, ReplayResult
from neftecode.application.ports import RobustnessEvaluator

__all__ = ["ExecutionState", "HISTORICAL", "MODES", "ReplayDecisions", "ReplayError", "SIMULATED",
           "compare_runs", "versions"]


@dataclass
class ReplayDecisions:

    scenario: Scenario
    raw_scenario: dict | None = None
    budget: int = DEFAULT_BUDGET
    orchestrator: MakeDecision = field(init=False)
    robustness_evaluator: RobustnessEvaluator | None = None
    tank_estimate_factory: object | None = None
    scenario_parser: object | None = None

    def __post_init__(self):
        self.orchestrator = MakeDecision(self.scenario, robustness_evaluator=self.robustness_evaluator,
                                         tank_estimate_factory=self.tank_estimate_factory,
                                         scenario_parser=self.scenario_parser)

    def step(self, mode: str, state: dict | None = None, execution: ExecutionState | None = None,
             future_truth: dict | None = None) -> dict:
        if mode not in MODES:
            raise ReplayError(f"Неизвестный режим воспроизведения: {mode}")
        if mode == HISTORICAL and execution is not None and execution.executed:
            raise ReplayError("Историческое воспроизведение не может продолжаться так, будто "
                              "рекомендация была исполнена: история уже содержит действия оператора")
        confirmed = execution.confirmed_controls() if execution is not None else ()
        kwargs = {"state": state, "confirmed": confirmed, "budget": self.budget,
                  "raw_scenario": self.raw_scenario}
        if mode == SIMULATED and execution is not None:
            kwargs.update(initial_tanks=execution.tanks,
                          current_operation=execution.current_operation)
        decision = self.orchestrator.decide(**kwargs)
        return {
            "mode": mode,
            "decision": decision,
            "versions": versions(self.scenario, self.raw_scenario),
            "evaluation_only": dict(future_truth or {}),
            "note": ("Историческое решение и модельное исполнение разделены: история не "
                     "показывает, что произошло бы после неисполненного действия."
                     if mode == HISTORICAL else
                     "Модельное исполнение. Числа получены в сценарной среде, а не на заводе."),
        }

    def run(self, moments, mode: str = SIMULATED, execution: ExecutionState | None = None) -> dict:
        state = execution or (ExecutionState.from_scenario(self.scenario)
                              if mode == SIMULATED else None)
        records = []
        for moment in moments:
            if mode == SIMULATED and state is not None:
                state = self._advance_to(state, moment.get("at"))
            record = self.step(mode, state=moment.get("state"), execution=state,
                               future_truth=moment.get("future_truth"))
            records.append({"at": moment.get("at"), **record})
            if mode == SIMULATED and state is not None:
                state = self._apply(state, moment, record["decision"])
        return {"mode": mode, "records": records,
                "final_execution": state.to_dict() if state is not None else None,
                "separation": "Результаты истории и моделирования не смешиваются: режим указан "
                "у каждой записи."}

    def execute(self, command: ReplayCommand) -> ReplayResult:
        if not isinstance(command, ReplayCommand):
            raise TypeError("ReplayDecisions.execute expects ReplayCommand")
        return self.run(command.moments, mode=command.mode, execution=command.execution)

    def _apply(self, state: ExecutionState, moment: dict, decision: dict) -> ExecutionState:
        confirmation = moment.get("confirm")
        if not confirmation:
            return state
        at = confirmation.get("confirmed_at", moment.get("at"))
        action = PendingAction(confirmation["action_id"], confirmation["proposed_at"],
                               dict(confirmation["controls"]),
                               confirmation.get("expected_response_hours", 2.0))
        state = state.confirm(action, at)
        confirmed_at = datetime.fromisoformat(str(at))
        moment_at = moment.get("at")
        if moment_at is not None and confirmed_at != datetime.fromisoformat(str(moment_at)):
            raise ReplayError("Подтверждение должно совпадать с моментом решения")
        operation = dict(state.current_operation or {})
        operation.update({key: confirmation[key] for key in
                          ("recipe", "throughput_tph", "additive_dose", "properties")
                          if key in confirmation})
        operation["controls"] = {**operation.get("controls", {}), **confirmation["controls"]}
        known = self.orchestrator.planner.base_controls()
        if set(operation.get("controls", {})) - set(known):
            raise ReplayError("Подтверждение содержит неизвестную уставку")
        for stage in self.scenario.stages.values():
            for name, spec in stage.controls.items():
                value = operation["controls"].get(name)
                if not isinstance(value, (int, float)) or not math.isfinite(value) or not spec["min"].value <= value <= spec["max"].value:
                    raise ReplayError(f"Подтверждённая уставка {name} вне диапазона")
        max_dose = self.scenario.additive.max_dose_fraction.value if self.scenario.additive else 0.0
        if operation.get("additive_dose", 0.0) > max_dose:
            raise ReplayError("Подтверждённая доза превышает предел")
        if set(operation.get("recipe", {})) - set(state.tanks):
            raise ReplayError("Рецепт содержит неизвестный резервуар")
        return state.set_operation(operation)

    def _advance_to(self, state: ExecutionState, at) -> ExecutionState:
        if at is None:
            raise ReplayError("У симулированного момента обязательно время at")
        try:
            current = datetime.fromisoformat(str(at))
        except ValueError as exc:
            raise ReplayError(f"Некорректное время момента: {at!r}") from exc
        if state.last_at is None:
            return replace(state, last_at=current.isoformat())
        previous = datetime.fromisoformat(state.last_at)
        hours = (current - previous).total_seconds() / 3600
        if not math.isfinite(hours) or hours < 0:
            raise ReplayError("Моменты симуляции должны идти по времени вперёд")
        if hours == 0:
            return state
        operation = state.current_operation or {}
        recipe = operation.get("recipe", {})
        throughput = operation.get("throughput_tph", 0.0)
        ExecutionState._validate_operation(operation)
        step_hours = self.scenario.horizon.step_minutes / 60.0
        updated = state
        elapsed = 0.0
        pending = self.orchestrator.planner.confirmed_with_operation(
            updated.confirmed_controls(), updated.current_operation)
        while elapsed < hours - 1e-9:
            duration = min(step_hours, hours - elapsed)
            inflow = self.orchestrator.planner.inflow_properties(elapsed, pending)
            result = draw_step(updated.tanks, recipe, float(throughput), duration, inflow)
            if not result.feasible:
                raise ReplayError("Симуляция не может продолжиться: " + "; ".join(result.reasons))
            updated = replace(updated, tanks=result.tanks)
            elapsed += duration
        return replace(updated, clock_hours=updated.clock_hours + hours, last_at=current.isoformat())


def compare_runs(first: dict, second: dict) -> dict:
    same = []
    for a, b in zip(first["records"], second["records"]):
        same.append({
            "at": a.get("at"),
            "same_status": a["decision"]["status"] == b["decision"]["status"],
            "same_decision_id": a["decision"]["decision_id"] == b["decision"]["decision_id"],
        })
    same_length = len(first["records"]) == len(second["records"])
    return {"n": len(same), "identical": same_length and all(r["same_decision_id"] for r in same),
            "same_length": same_length, "per_moment": same}
