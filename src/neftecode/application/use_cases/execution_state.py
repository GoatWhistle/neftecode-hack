from dataclasses import dataclass, replace
from datetime import datetime, timedelta
import hashlib
import json
import math

from neftecode.domain.shared.actions import PendingAction
from neftecode.domain.production.state import TankState
from neftecode.domain.production.inventory import initial_state
from neftecode.domain.production.scenario import Scenario
from .plan_operation import PlanOperation


HISTORICAL = "historical"
SIMULATED = "simulated"
MODES = (HISTORICAL, SIMULATED)


class ReplayError(ValueError):
    pass


@dataclass
class ExecutionState:

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
    payload = json.dumps(raw_scenario if raw_scenario is not None else scenario.to_dict(),
                         sort_keys=True, ensure_ascii=False)
    return {"scenario_id": scenario.scenario_id,
            "scenario_fingerprint": hashlib.sha256(payload.encode()).hexdigest()[:16],
            "horizon_hours": scenario.horizon.hours,
            "models": {"avt": scenario.stages["avt"].model.get("kind"),
                       "hydrotreating": scenario.stages["hydrotreating"].model.get("kind")}}
