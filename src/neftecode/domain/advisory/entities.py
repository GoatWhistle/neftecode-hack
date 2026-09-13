from dataclasses import dataclass, field

from neftecode.domain.shared.primitives import (ContractError, QUALITIES, PASS, FAIL, UNKNOWN,
    CHECK_STATUSES, SCENARIO_SCOPE, CONFIRMED_SCOPE, DECISION_STATUSES, HOLD, REFUSE,
    RECOMMEND_SCENARIO, _finite, _clean_number, _time)

from neftecode.domain.monitoring.entities import ForecastValue

@dataclass(frozen=True)
class PlanStep:
    """One step of a short plan: what is set, what is blended, how much is produced."""

    time_hours: float
    controls: dict[str, float] = field(default_factory=dict)
    recipe: dict[str, float] = field(default_factory=dict)
    throughput_tph: float = 0.0
    additive_dose: float = 0.0

    def __post_init__(self):
        if not _finite(self.time_hours) or self.time_hours < 0:
            raise ContractError("PlanStep.time_hours: время шага должно быть конечным и неотрицательным")
        if self.recipe:
            total = sum(self.recipe.values())
            if abs(total - 1.0) > 1e-6:
                raise ContractError(f"PlanStep[{self.time_hours} ч].recipe: доли дают {total:.6f}, требуется 1.0")
            negative = [k for k, v in self.recipe.items() if v < -1e-9]
            if negative:
                raise ContractError(f"PlanStep[{self.time_hours} ч].recipe: отрицательные доли {negative}")
        if not 0 <= self.additive_dose <= 1:
            raise ContractError("PlanStep.additive_dose_fraction: доза вне диапазона [0, 1]")

    def to_dict(self) -> dict:
        return {"time_hours": self.time_hours, "controls": dict(self.controls), "recipe": dict(self.recipe),
                "throughput_tph": self.throughput_tph,
                "additive_dose_fraction": self.additive_dose}

    def to_advice_dict(self) -> dict:
        """Serialize the established advisor payload without changing its wire contract."""
        return {"time_hours": self.time_hours, "controls": dict(self.controls),
                "recipe": dict(self.recipe), "throughput_tph": self.throughput_tph,
                "additive_dose": self.additive_dose}

    @property
    def additive_dose_fraction(self) -> float:
        return self.additive_dose

    @classmethod
    def from_dict(cls, raw: dict) -> "PlanStep":
        return cls(raw["time_hours"], dict(raw.get("controls", {})), dict(raw.get("recipe", {})),
                   raw.get("throughput_tph", 0.0), raw.get("additive_dose", raw.get("additive_dose_fraction", 0.0)))
@dataclass(frozen=True)
class ActionPlan:
    """A short sequence of steps. Only the first one is an immediate instruction."""

    plan_id: str
    steps: tuple[PlanStep, ...]
    scope: str = SCENARIO_SCOPE
    execution_conditions: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()

    def __post_init__(self):
        if not self.steps:
            raise ContractError("ActionPlan.steps: план без шагов не является планом")
        times = [s.time_hours for s in self.steps]
        if times != sorted(times) or len(set(times)) != len(times):
            raise ContractError("ActionPlan.steps: шаги должны идти строго по возрастанию времени")
        if times[0] != 0:
            raise ContractError("ActionPlan.steps: первый шаг обязан начинаться в момент решения (0 ч)")
        if self.scope not in (SCENARIO_SCOPE, CONFIRMED_SCOPE):
            raise ContractError(f"ActionPlan.scope: ожидается {SCENARIO_SCOPE} или {CONFIRMED_SCOPE}")

    @property
    def immediate(self) -> PlanStep:
        return self.steps[0]

    @property
    def horizon_hours(self) -> float:
        return self.steps[-1].time_hours

    def is_hold(self, current_controls: dict, current_recipe: dict) -> bool:
        """Keeping the regime is a candidate like any other, and must be recognisable."""
        first = self.immediate
        same_controls = all(abs(first.controls.get(k, v) - v) < 1e-9 for k, v in current_controls.items())
        same_recipe = all(abs(first.recipe.get(k, v) - v) < 1e-9 for k, v in current_recipe.items())
        return len(self.steps) == 1 and same_controls and same_recipe

    def to_dict(self) -> dict:
        return {"plan_id": self.plan_id, "steps": [s.to_dict() for s in self.steps], "scope": self.scope,
                "execution_conditions": list(self.execution_conditions), "assumptions": list(self.assumptions)}

    @classmethod
    def from_dict(cls, raw: dict) -> "ActionPlan":
        return cls(raw["plan_id"], tuple(PlanStep.from_dict(s) for s in raw["steps"]),
                   raw.get("scope", SCENARIO_SCOPE), tuple(raw.get("execution_conditions", ())),
                   tuple(raw.get("assumptions", ())))
@dataclass(frozen=True)
class TrajectoryPoint:
    """State of the chain at one time of the plan. A missing quality stays None."""

    time_hours: float
    qualities: dict[str, float | None]
    inventories: dict[str, float]
    production_tph: float = 0.0
    cost_proxy: float = 0.0
    severity_proxy: float | None = None
    applicability: str = "in_region"
    controls: dict[str, float] = field(default_factory=dict)
    recipe: dict[str, float] = field(default_factory=dict)
    throughput_tph: float | None = None
    additive_dose: float = 0.0
    inventory_reasons: tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "qualities",
                           {name: _clean_number(self.qualities.get(name), f"TrajectoryPoint.{name}")
                            for name in QUALITIES})
        object.__setattr__(self, "severity_proxy", _clean_number(self.severity_proxy, "TrajectoryPoint.severity_proxy"))
        if self.throughput_tph is None:
            object.__setattr__(self, "throughput_tph", self.production_tph)
        # Gate trajectory points carry raw values so the gate can report violations;
        # standalone contract points still reject an explicitly negative inventory.
        negative = [k for k, v in self.inventories.items() if v is not None and v < -1e-9]
        if self.controls or self.recipe:
            negative = []
        if negative:
            raise ContractError(f"TrajectoryPoint[{self.time_hours} ч]: отрицательные остатки {negative}")

    def unknown_qualities(self) -> list[str]:
        return [name for name, value in self.qualities.items() if value is None]

    def to_dict(self) -> dict:
        return {"time_hours": self.time_hours, "qualities": dict(self.qualities),
                "inventories": dict(self.inventories), "production_tph": self.production_tph,
                "cost_proxy": self.cost_proxy, "severity_proxy": self.severity_proxy,
                "applicability": self.applicability, "controls": dict(self.controls),
                "recipe": dict(self.recipe), "throughput_tph": self.throughput_tph,
                "additive_dose": self.additive_dose, "inventory_reasons": list(self.inventory_reasons)}

    @classmethod
    def from_dict(cls, raw: dict) -> "TrajectoryPoint":
        return cls(raw["time_hours"], dict(raw["qualities"]), dict(raw["inventories"]),
                   raw.get("production_tph", 0.0), raw.get("cost_proxy", 0.0),
                   raw.get("severity_proxy"), raw.get("applicability", "unknown"),
                   dict(raw.get("controls", {})), dict(raw.get("recipe", {})),
                   raw.get("throughput_tph"), raw.get("additive_dose", 0.0),
                   tuple(raw.get("inventory_reasons", ())))
@dataclass(frozen=True)
class TrajectoryEstimate:
    plan_id: str
    timeline: tuple[TrajectoryPoint, ...]
    model_versions: dict[str, str] = field(default_factory=dict)
    sensitivity_results: tuple[dict, ...] = ()
    scope: str = SCENARIO_SCOPE

    def __post_init__(self):
        if not self.timeline:
            raise ContractError("TrajectoryEstimate.timeline: пустая траектория ничего не подтверждает")

    @property
    def terminal_inventory(self) -> dict[str, float]:
        return dict(self.timeline[-1].inventories)

    def total_cost(self) -> float:
        return sum(p.cost_proxy for p in self.timeline)

    def to_dict(self) -> dict:
        return {"plan_id": self.plan_id, "timeline": [p.to_dict() for p in self.timeline],
                "model_versions": dict(self.model_versions),
                "sensitivity_results": list(self.sensitivity_results), "scope": self.scope,
                "terminal_inventory": self.terminal_inventory}

    @classmethod
    def from_dict(cls, raw: dict) -> "TrajectoryEstimate":
        return cls(raw["plan_id"], tuple(TrajectoryPoint.from_dict(p) for p in raw["timeline"]),
                   dict(raw.get("model_versions", {})), tuple(raw.get("sensitivity_results", ())),
                   raw.get("scope", SCENARIO_SCOPE))
@dataclass(frozen=True)
class CheckResult:
    """One mandatory check at one time. Status `unknown` never counts as satisfied."""

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
    """Verdict over the whole trajectory. Feasibility is derived, never asserted by a caller."""

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
    """The advisor's answer, always carrying its scope and the reason behind it."""

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
