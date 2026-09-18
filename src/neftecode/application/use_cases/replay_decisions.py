"""Replaying decisions: the same core, on history and in the scenario environment.

Two modes, deliberately not mixed in the output:

* **historical** — the decision core runs at a past moment using only what was available then.
  The future laboratory value exists, but it goes to the evaluator *after* the decision and
  never into the state the agents see.
* **simulated** — actions are applied through a separate execution state with its own material
  balance. This is where an alternative control can be studied at all, because history contains
  no observation of what an unexecuted action would have produced.

Because of that split, a historical replay must never be continued as though a recommendation
had been carried out. The history is the history: it already contains whatever the operator
actually did, and nothing else.
"""
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
import hashlib
import json
import math

from neftecode.domain.shared.actions import PendingAction
from neftecode.domain.production.state import TankState
from neftecode.domain.production.inventory import draw_step, initial_state
from .plan_operation import PlanOperation
from .make_decision import MakeDecision
from neftecode.domain.production.scenario import Scenario
from neftecode.application.contracts import ReplayCommand, ReplayResult
from neftecode.application.ports import RobustnessEvaluator

HISTORICAL = "historical"
SIMULATED = "simulated"
MODES = (HISTORICAL, SIMULATED)


class ReplayError(ValueError):
    """Raised when a replay is asked to mix history with unexecuted actions."""


@dataclass
class ExecutionState:
    """What the simulated plant actually holds and what has actually been executed.

    Kept apart from the advisor's state so that issuing advice cannot change the plant, and
    so that a pause and a resume lose neither inventory nor a pending action.
    """

    tanks: dict[str, TankState]
    executed: tuple[PendingAction, ...] = ()
    clock_hours: float = 0.0
    current_operation: dict | None = None
    last_at: str | None = None
    executed_operations: tuple[dict, ...] = ()

    @classmethod
    def from_scenario(cls, scenario: Scenario) -> "ExecutionState":
        operation = scenario.current_operation
        controls = PlanOperation(scenario).base_controls()
        return cls(initial_state(scenario), current_operation={
            "recipe": dict(operation.recipe),
            "throughput_tph": operation.throughput.value,
            "additive_dose": 0.0,
            "controls": controls,
        })

    def confirm(self, action: PendingAction, at) -> "ExecutionState":
        """Record an operator confirmation. Only confirmed actions reach the plant."""
        if any(a.action_id == action.action_id for a in self.executed):
            raise ReplayError(f"Действие {action.action_id} уже исполнено: повторное применение "
                              f"привело бы к двойному учёту")
        confirmed = action.confirm(at)
        operation = dict(self.current_operation or {})
        if operation:
            operation["controls"] = {**operation.get("controls", {}), **action.controls}
        return replace(self, executed=self.executed + (confirmed,),
                       last_at=self.last_at or confirmed.confirmed_at,
                       current_operation=operation or None)

    def draw(self, drawn: dict[str, float]) -> "ExecutionState":
        tanks = dict(self.tanks)
        for tank_id, mass in drawn.items():
            if not isinstance(mass, (int, float)) or isinstance(mass, bool) or not math.isfinite(mass) or mass < 0:
                raise ReplayError("Отбор должен быть конечным и неотрицательным")
            if mass == 0:
                continue
            if tank_id not in tanks:
                raise ReplayError(f"Резервуар {tank_id} отсутствует в состоянии исполнения")
            tanks[tank_id] = tanks[tank_id].draw(mass)
        return replace(self, tanks=tanks)

    def advance(self, hours: float) -> "ExecutionState":
        if not isinstance(hours, (int, float)) or isinstance(hours, bool) or not math.isfinite(hours) or hours < 0:
            raise ReplayError("Время продвижения должно быть конечным и неотрицательным")
        last_at = self.last_at
        if last_at is not None:
            last_at = (datetime.fromisoformat(last_at) + timedelta(hours=hours)).isoformat()
        return replace(self, clock_hours=self.clock_hours + hours, last_at=last_at)

    def confirmed_controls(self) -> tuple:
        """Confirmed actions in the form the planner consumes."""
        if self.last_at is None:
            return tuple((0.0, dict(a.controls)) for a in self.executed)
        now = datetime.fromisoformat(self.last_at)
        return tuple(((datetime.fromisoformat(a.confirmed_at) - now).total_seconds() / 3600,
                      dict(a.controls)) for a in self.executed)

    def set_operation(self, operation: dict) -> "ExecutionState":
        ExecutionState._validate_operation(operation)
        return replace(self, current_operation=dict(operation),
                       executed_operations=self.executed_operations + (dict(operation),))

    @staticmethod
    def _validate_operation(operation: dict):
        recipe = operation.get("recipe")
        flow = operation.get("throughput_tph")
        dose = operation.get("additive_dose", 0.0)
        if not isinstance(recipe, dict) or not recipe or any(
                not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) or v < 0
                for v in recipe.values()) or abs(sum(recipe.values()) - 1.0) > 1e-6:
            raise ReplayError("Текущая операция содержит некорректные доли рецепта")
        if not isinstance(flow, (int, float)) or isinstance(flow, bool) or not math.isfinite(flow) or flow < 0:
            raise ReplayError("Текущая операция содержит некорректный выпуск")
        if not isinstance(dose, (int, float)) or isinstance(dose, bool) or not math.isfinite(dose) or dose < 0:
            raise ReplayError("Текущая операция содержит некорректную дозу присадки")

    def to_dict(self) -> dict:
        return {"clock_hours": self.clock_hours,
                "tanks": {k: v.to_dict() for k, v in self.tanks.items()},
                "executed": [a.to_dict() for a in self.executed],
                "current_operation": self.current_operation,
                "last_at": self.last_at,
                "executed_operations": list(self.executed_operations)}

    @classmethod
    def from_dict(cls, raw: dict) -> "ExecutionState":
        clock = raw.get("clock_hours", 0.0)
        if not isinstance(clock, (int, float)) or isinstance(clock, bool) or not math.isfinite(clock) or clock < 0:
            raise ReplayError("Сохраненные часы должны быть конечными и неотрицательными")
        operation = raw.get("current_operation")
        if operation is not None:
            cls._validate_operation(operation)
        return cls({k: TankState.from_dict(v) for k, v in raw["tanks"].items()},
                   tuple(PendingAction.from_dict(a) for a in raw.get("executed", ())), clock,
                   operation, raw.get("last_at"),
                   tuple(raw.get("executed_operations", ())))


def versions(scenario: Scenario, raw_scenario: dict | None = None) -> dict:
    """Fingerprint of everything a replay depended on, so a rerun can be compared."""
    payload = json.dumps(raw_scenario if raw_scenario is not None else scenario.to_dict(),
                         sort_keys=True, ensure_ascii=False)
    return {"scenario_id": scenario.scenario_id,
            "scenario_fingerprint": hashlib.sha256(payload.encode()).hexdigest()[:16],
            "horizon_hours": scenario.horizon.hours,
            "models": {"avt": scenario.stages["avt"].model.get("kind"),
                       "hydrotreating": scenario.stages["hydrotreating"].model.get("kind")}}


@dataclass
class ReplayDecisions:
    """Runs the same decision core in either mode and records what it depended on."""

    scenario: Scenario
    raw_scenario: dict | None = None
    budget: int = 400
    orchestrator: MakeDecision = field(init=False)
    robustness_evaluator: RobustnessEvaluator | None = None

    def __post_init__(self):
        self.orchestrator = MakeDecision(self.scenario, robustness_evaluator=self.robustness_evaluator)

    def step(self, mode: str, state: dict | None = None, execution: ExecutionState | None = None,
             future_truth: dict | None = None) -> dict:
        """One decision. `future_truth` is returned for evaluation and never shown to the agents."""
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
            # The evaluator gets the truth; the agents never saw it.
            "evaluation_only": dict(future_truth or {}),
            "note": ("Историческое решение и модельное исполнение разделены: история не "
                     "показывает, что произошло бы после неисполненного действия."
                     if mode == HISTORICAL else
                     "Модельное исполнение. Числа получены в сценарной среде, а не на заводе."),
        }

    def run(self, moments, mode: str = SIMULATED, execution: ExecutionState | None = None) -> dict:
        """ReplayDecisions a list of moments. Returns each decision plus the final execution state."""
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
        """Application entry point for deterministic replay."""
        if not isinstance(command, ReplayCommand):
            raise TypeError("ReplayDecisions.execute expects ReplayCommand")
        return self.run(command.moments, mode=command.mode, execution=command.execution)

    def _apply(self, state: ExecutionState, moment: dict, decision: dict) -> ExecutionState:
        """Apply only what the operator confirmed in this moment, never the advice itself."""
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
        """Advance material balance to a moment before asking for advice."""
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
    """Are two replays numerically the same decision by decision?"""
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
