from dataclasses import dataclass, field

from neftecode.domain.advisory.entities import PlanStep
from neftecode.domain.production.blending import Blender
from neftecode.domain.production.economics import Economics
from neftecode.domain.advisory.optimizer import rank
from neftecode.domain.production.process import ChainModel
from neftecode.domain.production.scenario import Scenario
from neftecode.application.contracts import PlanningCommand, PlanningResult
from .planning.builder import PlanBuilderMixin
from .planning.candidate import PlanCandidate, PlannerError
from .planning.evaluation import PlanEvaluationMixin

__all__ = ["PlanOperation", "PlanCandidate", "PlannerError", "PlanStep"]


@dataclass
class PlanOperation(PlanBuilderMixin, PlanEvaluationMixin):

    scenario: Scenario
    chain: ChainModel = field(init=False)
    blender: Blender = field(init=False)
    economics: Economics = field(init=False)

    def __post_init__(self):
        self.chain = ChainModel(self.scenario)
        self.blender = Blender(self.scenario)
        self.economics = Economics(self.scenario)


    def grid(self) -> list[float]:
        return self.scenario.horizon.times_hours()

    def base_controls(self) -> dict[str, float]:
        return self.chain.current_controls()

    def confirmed_with_operation(self, confirmed=(), current_operation=None):
        confirmed = tuple(confirmed)
        if current_operation is None:
            return confirmed
        dated = {name for _, controls in confirmed for name in controls}
        base = self.base_controls()
        standing = {k: v for k, v in current_operation["controls"].items()
                    if k not in dated and abs(v - base.get(k, v)) > 1e-9}
        age = max(stage.response_lag_hours.value for stage in self.scenario.stages.values())
        return ((-age, standing),) + confirmed if standing else confirmed

    def inflow_properties(self, time_hours: float, pending=()) -> dict[str, dict[str, float | None]]:
        incoming = self.chain.run_at(time_hours, pending)
        tank = self.scenario.tank(self._main_id())
        sulfur = incoming.sulfur_mgkg if tank.sulfur_from_chain else tank.property_value("sulfur_mgkg")
        declared = tank.properties.get("sulfur_mgkg")
        if tank.inflow_sulfur is not None:
            ratio = self._response_ratio(time_hours, pending)
            sulfur = None if ratio is None else tank.inflow_sulfur.value * ratio
        elif declared is not None and declared.source in ("derived", "measured"):
            level = self._main_sulfur()
            ratio = self._response_ratio(time_hours, pending)
            sulfur = None if level is None or ratio is None else level * ratio
        return {self._main_id(): {"sulfur_mgkg": sulfur, "t95_c": incoming.t95_c,
                                 "cetane_number": tank.property_value("cetane_number"),
                                 "density_kgm3": tank.property_value("density_kgm3")}}


    def plan(self, confirmed=(), budget: int = 120) -> dict:
        plans, info = self.build_plans(budget)
        evaluations = []
        by_id = {}
        for candidate in plans:
            try:
                evaluation = self.evaluate(candidate, confirmed)
            except (PlannerError, ValueError):
                continue
            evaluations.append(evaluation)
            by_id[candidate.plan_id] = candidate
        min_gain = float(self.scenario.policy.get("min_useful_gain", 0.0))
        result = rank(evaluations, hold_id="hold", min_useful_gain=min_gain)
        chosen_id = result["selected"]["candidate_id"] if result["selected"] else None
        result["selected_plan"] = by_id[chosen_id].to_dict() if chosen_id in by_id else None
        result["search"] = info
        result["confirmed_actions"] = [{"applied_at_hours": at, "controls": dict(controls)}
                                       for at, controls in confirmed]
        result["note"] = ("Выданный план не считается исполненным. Он войдёт в состояние только "
                          "как подтверждённое оператором действие.")
        return result

    def execute(self, command: PlanningCommand) -> PlanningResult:
        if not isinstance(command, PlanningCommand):
            raise TypeError("PlanOperation.execute expects PlanningCommand")
        return self.plan(confirmed=command.confirmed, budget=command.budget)
