from dataclasses import dataclass, field

from neftecode.domain.shared.primitives import (ContractError, PASS, FAIL, UNKNOWN,
    CHECK_STATUSES, SCENARIO_SCOPE, DECISION_STATUSES, HOLD, REFUSE,
    RECOMMEND_SCENARIO, _clean_number, _time)

from neftecode.domain.monitoring.entities import ForecastValue

from .plan import ActionPlan, PlanStep
from .trajectory import TrajectoryEstimate, TrajectoryPoint

__all__ = ["ActionPlan", "CheckResult", "Decision", "GateResult", "PlanStep", "TrajectoryEstimate",
           "TrajectoryPoint"]


@dataclass(frozen=True)
class CheckResult:

    constraint_id: str
    status: str
    observed: float | None = None
    limit: float | None = None
    time_hours: float | None = None
    reason: str = ""

    def __post_init__(self):
        if self.status not in CHECK_STATUSES:
            raise ContractError(f"CheckResult[{self.constraint_id}].status: ожидается одно из {CHECK_STATUSES}")
        object.__setattr__(self, "observed", _clean_number(self.observed, "CheckResult.observed"))
        object.__setattr__(self, "limit", _clean_number(self.limit, "CheckResult.limit"))
        if self.status in (FAIL, UNKNOWN) and not self.reason:
            raise ContractError(f"CheckResult[{self.constraint_id}]: запрет или неизвестность обязаны "
                                f"назвать причину")

    @property
    def satisfied(self) -> bool:
        return self.status == PASS

    def to_dict(self) -> dict:
        return {"constraint_id": self.constraint_id, "status": self.status, "observed": self.observed,
                "limit": self.limit, "time_hours": self.time_hours, "reason": self.reason}

    @classmethod
    def from_dict(cls, raw: dict) -> "CheckResult":
        return cls(raw["constraint_id"], raw["status"], raw.get("observed"), raw.get("limit"),
                   raw.get("time_hours"), raw.get("reason", ""))
@dataclass(frozen=True)
class GateResult:

    plan_id: str
    checks: tuple[CheckResult, ...]

    def __post_init__(self):
        if not self.checks:
            raise ContractError("GateResult.checks: план без единой проверки не может быть признан допустимым")

    @property
    def feasible(self) -> bool:
        return all(c.satisfied for c in self.checks)

    @property
    def first_violation(self) -> CheckResult | None:
        failed = [c for c in self.checks if c.status == FAIL]
        if not failed:
            return None
        return min(failed, key=lambda c: (c.time_hours if c.time_hours is not None else -1.0))

    def unknown_requirements(self) -> tuple[CheckResult, ...]:
        return tuple(c for c in self.checks if c.status == UNKNOWN)

    def rejection_reasons(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(c.reason for c in self.checks if c.status in (FAIL, UNKNOWN)))

    def to_dict(self) -> dict:
        return {"plan_id": self.plan_id, "feasible": self.feasible,
                "checks": [c.to_dict() for c in self.checks],
                "first_violation": self.first_violation.to_dict() if self.first_violation else None,
                "unknown_requirements": [c.to_dict() for c in self.unknown_requirements()],
                "rejection_reasons": list(self.rejection_reasons())}

    @classmethod
    def from_dict(cls, raw: dict) -> "GateResult":
        return cls(raw["plan_id"], tuple(CheckResult.from_dict(c) for c in raw["checks"]))
@dataclass(frozen=True)
class Decision:

    decision_id: str
    as_of: str
    status: str
    reason: str
    scenario_id: str
    selected_plan: ActionPlan | None = None
    expected_outcome: TrajectoryEstimate | None = None
    gate: GateResult | None = None
    alternatives: tuple[dict, ...] = ()
    rejected: tuple[dict, ...] = ()
    forecasts: tuple[ForecastValue, ...] = ()
    agent_trace: tuple[dict, ...] = ()
    model_versions: dict[str, str] = field(default_factory=dict)
    next_review_at: str | None = None
    reconsideration_conditions: tuple[str, ...] = ()
    scope: str = SCENARIO_SCOPE
    commercial_release_allowed: bool = False

    def __post_init__(self):
        object.__setattr__(self, "as_of", _time(self.as_of, "Decision.as_of"))
        object.__setattr__(self, "next_review_at", _time(self.next_review_at, "Decision.next_review_at", required=False))
        if self.status not in DECISION_STATUSES:
            raise ContractError(f"Decision.status: ожидается одно из {DECISION_STATUSES}")
        if not self.reason.strip():
            raise ContractError("Decision.reason: решение обязано назвать причину")
        if self.status == REFUSE and self.selected_plan is not None:
            raise ContractError("Decision: отказ не может нести выбранный план")
        if self.status in (HOLD, RECOMMEND_SCENARIO) and self.selected_plan is None:
            raise ContractError(f"Decision: статус {self.status} требует выбранного плана")
        if self.selected_plan is not None and self.gate is not None and not self.gate.feasible:
            raise ContractError("Decision: выбран план, не прошедший обязательные проверки")
        if self.commercial_release_allowed:
            raise ContractError("Decision: разрешение промышленного выпуска не выдаётся этим прототипом; "
                                "проверены не все требуемые свойства")

    @property
    def immediate_action(self) -> PlanStep | None:
        return self.selected_plan.immediate if self.selected_plan else None

    def to_dict(self) -> dict:
        return {"decision_id": self.decision_id, "as_of": self.as_of, "status": self.status,
                "reason": self.reason, "scenario_id": self.scenario_id,
                "selected_plan": self.selected_plan.to_dict() if self.selected_plan else None,
                "expected_outcome": self.expected_outcome.to_dict() if self.expected_outcome else None,
                "gate": self.gate.to_dict() if self.gate else None,
                "alternatives": list(self.alternatives), "rejected": list(self.rejected),
                "forecasts": [f.to_dict() for f in self.forecasts],
                "agent_trace": list(self.agent_trace), "model_versions": dict(self.model_versions),
                "next_review_at": self.next_review_at,
                "reconsideration_conditions": list(self.reconsideration_conditions),
                "scope": self.scope, "commercial_release_allowed": self.commercial_release_allowed}

    @classmethod
    def from_dict(cls, raw: dict) -> "Decision":
        plan = raw.get("selected_plan")
        outcome = raw.get("expected_outcome")
        gate = raw.get("gate")
        return cls(raw["decision_id"], raw["as_of"], raw["status"], raw["reason"], raw["scenario_id"],
                   ActionPlan.from_dict(plan) if plan else None,
                   TrajectoryEstimate.from_dict(outcome) if outcome else None,
                   GateResult.from_dict(gate) if gate else None,
                   tuple(raw.get("alternatives", ())), tuple(raw.get("rejected", ())),
                   tuple(ForecastValue.from_dict(f) for f in raw.get("forecasts", ())),
                   tuple(raw.get("agent_trace", ())), dict(raw.get("model_versions", {})),
                   raw.get("next_review_at"), tuple(raw.get("reconsideration_conditions", ())),
                   raw.get("scope", SCENARIO_SCOPE), raw.get("commercial_release_allowed", False))
