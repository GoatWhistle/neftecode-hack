from typing import Mapping, Protocol, Sequence

from neftecode.domain.advisory.entities import PlanStep
from neftecode.domain.production.scenario import Scenario
from neftecode.domain.production.state import TankState


class CandidatePlan(Protocol):
    plan_id: str
    steps: tuple[PlanStep, ...]


class RobustnessEvaluator(Protocol):
    def evaluate(self, scenario: Scenario, raw_scenario: Mapping[str, object], plan: CandidatePlan,
                 confirmed: Sequence[tuple[float, Mapping[str, float]]] = (),
                 initial_tanks: Mapping[str, TankState] | None = None,
                 current_operation: Mapping[str, object] | None = None) -> dict: ...
