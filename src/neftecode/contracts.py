"""Shared types passed between data, forecast, process models, agents and the interface.

Three rules are enforced here rather than left to each caller:

1. Unknown is a value. It never collapses into zero, into a passing check or into a
   permissive default. A check that could not be evaluated blocks the plan.
2. A proposed action is not an executed one. Only an operator confirmation moves a
   PendingAction into a state where its effect may be expected.
3. Every number keeps its unit, its time and where it came from, so a scenario constant
   cannot later be read back as a plant measurement.
"""
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
import math

from .scenario import QUALITIES, SOURCES

#: Result of one mandatory check. `unknown` is failure to evaluate, never a pass.
PASS, FAIL, UNKNOWN = "pass", "fail", "unknown"
CHECK_STATUSES = (PASS, FAIL, UNKNOWN)

#: Lifecycle of an action the advisor proposed.
PROPOSED, CONFIRMED, REJECTED, EXPIRED = "proposed", "confirmed", "rejected", "expired"
EXECUTION_STATUSES = (PROPOSED, CONFIRMED, REJECTED, EXPIRED)

#: Final decision statuses. `recommend` in the full industrial sense is not available yet.
HOLD, RECOMMEND_SCENARIO, REFUSE = "hold", "recommend_scenario", "refuse"
DECISION_STATUSES = (HOLD, RECOMMEND_SCENARIO, REFUSE)

#: Whether the result is confined to the synthetic scenario or covers confirmed plant behaviour.
SCENARIO_SCOPE, CONFIRMED_SCOPE = "synthetic_scenario", "confirmed_model"


class ContractError(ValueError):
    """Raised when a contract is violated, with a message naming the field."""


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _clean_number(value, where: str):
    """NaN and infinity become unknown rather than travelling through the system as numbers."""
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ContractError(f"{where}: ожидается число или None, получено {type(value).__name__}")
    return float(value) if math.isfinite(value) else None


def _time(value, where: str, required: bool = True) -> str | None:
    if value is None:
        if required:
            raise ContractError(f"{where}: время обязательно")
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    text = str(value)
    try:
        datetime.fromisoformat(text)
    except ValueError as exc:
        raise ContractError(f"{where}: время «{text}» не в формате ISO 8601") from exc
    return text


@dataclass(frozen=True)
class Observation:
    """One reading, keeping sample time and availability time apart."""

    tag_id: str
    source: str
    value: float | None
    unit: str
    measured_at: str
    available_at: str
    validity: str = "ok"
    issues: tuple[str, ...] = ()
    provenance: str = "given"

    VALIDITY = ("ok", "suspect", "unusable")

    def __post_init__(self):
        if not self.tag_id:
            raise ContractError("Observation.tag_id: обязательно")
        object.__setattr__(self, "value", _clean_number(self.value, f"Observation[{self.tag_id}].value"))
        object.__setattr__(self, "measured_at", _time(self.measured_at, f"Observation[{self.tag_id}].measured_at"))
        object.__setattr__(self, "available_at", _time(self.available_at, f"Observation[{self.tag_id}].available_at"))
        if self.available_at < self.measured_at:
            raise ContractError(f"Observation[{self.tag_id}]: результат не может быть доступен раньше измерения")
        if self.validity not in self.VALIDITY:
            raise ContractError(f"Observation[{self.tag_id}].validity: ожидается одно из {self.VALIDITY}")
        if self.provenance not in SOURCES:
            raise ContractError(f"Observation[{self.tag_id}].provenance: ожидается одно из {SOURCES}")

    @property
    def usable(self) -> bool:
        return self.validity == "ok" and self.value is not None

    def visible_at(self, when: str | datetime) -> bool:
        """A late sample appears only after available_at, never retroactively."""
        return self.available_at <= _time(when, "visible_at")

    def age_hours(self, when: str | datetime) -> float:
        return (datetime.fromisoformat(_time(when, "age_hours"))
                - datetime.fromisoformat(self.measured_at)).total_seconds() / 3600

    def to_dict(self) -> dict:
        return {"tag_id": self.tag_id, "source": self.source, "value": self.value, "unit": self.unit,
                "measured_at": self.measured_at, "available_at": self.available_at,
                "validity": self.validity, "issues": list(self.issues), "provenance": self.provenance}

    @classmethod
    def from_dict(cls, raw: dict) -> "Observation":
        return cls(raw["tag_id"], raw["source"], raw.get("value"), raw["unit"], raw["measured_at"],
                   raw["available_at"], raw.get("validity", "ok"), tuple(raw.get("issues", ())),
                   raw.get("provenance", "given"))


@dataclass(frozen=True)
class TankState:
    """Inventory and properties of one blending component at a point in time."""

    tank_id: str
    available: bool
    inventory_t: float
    properties: dict[str, float | None]
    inflow_tph: float = 0.0
    max_outflow_tph: float = 0.0
    observed_at: str | None = None
    provenance: str = "scenario"

    def __post_init__(self):
        if not _finite(self.inventory_t) or self.inventory_t < 0:
            raise ContractError(f"TankState[{self.tank_id}].inventory_t: остаток должен быть конечным и неотрицательным")
        cleaned = {name: _clean_number(self.properties.get(name), f"TankState[{self.tank_id}].{name}")
                   for name in QUALITIES}
        object.__setattr__(self, "properties", cleaned)
        object.__setattr__(self, "observed_at", _time(self.observed_at, "TankState.observed_at", required=False))
        if self.properties["sulfur_mgkg"] is None:
            raise ContractError(f"TankState[{self.tank_id}]: сера компонента обязательна для материального баланса")

    def unknown_properties(self) -> list[str]:
        return [name for name in QUALITIES if self.properties[name] is None]

    def draw(self, mass_t: float) -> "TankState":
        """Withdrawal that would go negative is an error, not a silent clamp to zero."""
        if not _finite(mass_t) or mass_t < 0:
            raise ContractError(f"TankState[{self.tank_id}].draw: масса отбора должна быть конечной и неотрицательной")
        if mass_t > self.inventory_t + 1e-9:
            raise ContractError(f"TankState[{self.tank_id}]: отбор {mass_t:.3f} т превышает остаток {self.inventory_t:.3f} т")
        return replace(self, inventory_t=max(0.0, self.inventory_t - mass_t))

    def add(self, mass_t: float) -> "TankState":
        if not _finite(mass_t) or mass_t < 0:
            raise ContractError(f"TankState[{self.tank_id}].add: масса притока должна быть конечной и неотрицательной")
        return replace(self, inventory_t=self.inventory_t + mass_t)

    def to_dict(self) -> dict:
        return {"tank_id": self.tank_id, "available": self.available, "inventory_t": self.inventory_t,
                "properties": dict(self.properties), "inflow_tph": self.inflow_tph,
                "max_outflow_tph": self.max_outflow_tph, "observed_at": self.observed_at,
                "provenance": self.provenance}

    @classmethod
    def from_dict(cls, raw: dict) -> "TankState":
        return cls(raw["tank_id"], raw["available"], raw["inventory_t"], dict(raw["properties"]),
                   raw.get("inflow_tph", 0.0), raw.get("max_outflow_tph", 0.0),
                   raw.get("observed_at"), raw.get("provenance", "scenario"))


@dataclass(frozen=True)
class PendingAction:
    """An advised action. Advice alone changes neither equipment nor inventory."""

    action_id: str
    proposed_at: str
    controls: dict[str, float]
    expected_response_hours: float
    execution_status: str = PROPOSED
    confirmed_at: str | None = None
    observed_response_status: str = "not_evaluated"

    def __post_init__(self):
        object.__setattr__(self, "proposed_at", _time(self.proposed_at, "PendingAction.proposed_at"))
        object.__setattr__(self, "confirmed_at", _time(self.confirmed_at, "PendingAction.confirmed_at", required=False))
        if self.execution_status not in EXECUTION_STATUSES:
            raise ContractError(f"PendingAction.execution_status: ожидается одно из {EXECUTION_STATUSES}")
        if self.execution_status == CONFIRMED and self.confirmed_at is None:
            raise ContractError("PendingAction: подтверждённое действие обязано иметь время подтверждения")
        if self.execution_status != CONFIRMED and self.confirmed_at is not None:
            raise ContractError("PendingAction: время подтверждения без статуса confirmed")
        if not _finite(self.expected_response_hours) or not 0 <= self.expected_response_hours <= 3:
            raise ContractError("PendingAction.expected_response_hours: ожидается 0–3 часа по уточнению эксперта")

    @property
    def executed(self) -> bool:
        """Only a confirmed action may be assumed to act on the plant."""
        return self.execution_status == CONFIRMED

    def effect_expected_at(self) -> str | None:
        """Unconfirmed advice has no expected effect time: it was never executed."""
        if not self.executed:
            return None
        start = datetime.fromisoformat(self.confirmed_at)
        return (start + timedelta(hours=self.expected_response_hours)).isoformat()

    def confirm(self, at) -> "PendingAction":
        if self.executed:
            raise ContractError(f"PendingAction[{self.action_id}]: действие уже подтверждено, повторное подтверждение "
                                f"привело бы к двойному учёту эффекта")
        return replace(self, execution_status=CONFIRMED, confirmed_at=_time(at, "PendingAction.confirm"))

    def to_dict(self) -> dict:
        return {"action_id": self.action_id, "proposed_at": self.proposed_at, "controls": dict(self.controls),
                "expected_response_hours": self.expected_response_hours,
                "execution_status": self.execution_status, "confirmed_at": self.confirmed_at,
                "observed_response_status": self.observed_response_status}

    @classmethod
    def from_dict(cls, raw: dict) -> "PendingAction":
        return cls(raw["action_id"], raw["proposed_at"], dict(raw["controls"]),
                   raw["expected_response_hours"], raw.get("execution_status", PROPOSED),
                   raw.get("confirmed_at"), raw.get("observed_response_status", "not_evaluated"))


@dataclass(frozen=True)
class PlantState:
    """Everything known at the moment of decision, and nothing that was not yet available."""

    as_of: str
    observations: tuple[Observation, ...] = ()
    features: dict[str, float | None] = field(default_factory=dict)
    tanks: tuple[TankState, ...] = ()
    pending_actions: tuple[PendingAction, ...] = ()
    current_controls: dict[str, float] = field(default_factory=dict)
    current_recipe: dict[str, float] = field(default_factory=dict)
    current_throughput_tph: float | None = None
    data_quality: dict = field(default_factory=dict)
    missing_inputs: tuple[str, ...] = ()
    operating_region: str = "unknown"
    origin: str = SCENARIO_SCOPE

    def __post_init__(self):
        object.__setattr__(self, "as_of", _time(self.as_of, "PlantState.as_of"))
        late = [o.tag_id for o in self.observations if not o.visible_at(self.as_of)]
        if late:
            raise ContractError(f"PlantState: наблюдения {', '.join(late)} ещё не были доступны на {self.as_of}; "
                                f"это утечка из будущего")
        if self.current_recipe:
            total = sum(self.current_recipe.values())
            if abs(total - 1.0) > 1e-6:
                raise ContractError(f"PlantState.current_recipe: доли дают {total:.6f}, требуется 1.0")
        object.__setattr__(self, "current_throughput_tph",
                           _clean_number(self.current_throughput_tph, "PlantState.current_throughput_tph"))

    def tank(self, tank_id: str) -> TankState:
        for t in self.tanks:
            if t.tank_id == tank_id:
                return t
        raise ContractError(f"PlantState: резервуар {tank_id} отсутствует в состоянии")

    def confirmed_actions(self) -> tuple[PendingAction, ...]:
        return tuple(a for a in self.pending_actions if a.executed)

    def to_dict(self) -> dict:
        return {"as_of": self.as_of, "observations": [o.to_dict() for o in self.observations],
                "features": dict(self.features), "tanks": [t.to_dict() for t in self.tanks],
                "pending_actions": [a.to_dict() for a in self.pending_actions],
                "current_controls": dict(self.current_controls), "current_recipe": dict(self.current_recipe),
                "current_throughput_tph": self.current_throughput_tph, "data_quality": dict(self.data_quality),
                "missing_inputs": list(self.missing_inputs), "operating_region": self.operating_region,
                "origin": self.origin}

    @classmethod
    def from_dict(cls, raw: dict) -> "PlantState":
        return cls(raw["as_of"],
                   tuple(Observation.from_dict(o) for o in raw.get("observations", ())),
                   dict(raw.get("features", {})),
                   tuple(TankState.from_dict(t) for t in raw.get("tanks", ())),
                   tuple(PendingAction.from_dict(a) for a in raw.get("pending_actions", ())),
                   dict(raw.get("current_controls", {})), dict(raw.get("current_recipe", {})),
                   raw.get("current_throughput_tph"), dict(raw.get("data_quality", {})),
                   tuple(raw.get("missing_inputs", ())), raw.get("operating_region", "unknown"),
                   raw.get("origin", SCENARIO_SCOPE))


@dataclass(frozen=True)
class ForecastValue:
    """A forecast of one quality, or an explicit statement that none is available."""

    target: str
    horizon_hours: float
    value: float | None
    lower: float | None
    upper: float | None
    model_version: str
    calibration_version: str | None = None
    valid_from: str | None = None
    applicability: str = "unknown"
    limitations: tuple[str, ...] = ()

    def __post_init__(self):
        for name in ("value", "lower", "upper"):
            object.__setattr__(self, name, _clean_number(getattr(self, name), f"ForecastValue.{name}"))
        object.__setattr__(self, "valid_from", _time(self.valid_from, "ForecastValue.valid_from", required=False))
        if self.available and not self.lower <= self.value <= self.upper:
            raise ContractError(f"ForecastValue[{self.target}]: границы {self.lower}…{self.upper} не окружают "
                                f"точечный прогноз {self.value}")

    @property
    def available(self) -> bool:
        return None not in (self.value, self.lower, self.upper)

    def usable_at(self, when) -> bool:
        """A model must not be applied before the moment its calibration existed."""
        return self.valid_from is None or self.valid_from <= _time(when, "ForecastValue.usable_at")

    def to_dict(self) -> dict:
        return {"target": self.target, "horizon_hours": self.horizon_hours, "value": self.value,
                "lower": self.lower, "upper": self.upper, "model_version": self.model_version,
                "calibration_version": self.calibration_version, "valid_from": self.valid_from,
                "applicability": self.applicability, "limitations": list(self.limitations)}

    @classmethod
    def from_dict(cls, raw: dict) -> "ForecastValue":
        return cls(raw["target"], raw["horizon_hours"], raw.get("value"), raw.get("lower"), raw.get("upper"),
                   raw["model_version"], raw.get("calibration_version"), raw.get("valid_from"),
                   raw.get("applicability", "unknown"), tuple(raw.get("limitations", ())))


@dataclass(frozen=True)
class PlanStep:
    """One step of a short plan: what is set, what is blended, how much is produced."""

    time_hours: float
    controls: dict[str, float] = field(default_factory=dict)
    recipe: dict[str, float] = field(default_factory=dict)
    throughput_tph: float = 0.0
    additive_dose_fraction: float = 0.0

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
        if not 0 <= self.additive_dose_fraction <= 1:
            raise ContractError("PlanStep.additive_dose_fraction: доза вне диапазона [0, 1]")

    def to_dict(self) -> dict:
        return {"time_hours": self.time_hours, "controls": dict(self.controls), "recipe": dict(self.recipe),
                "throughput_tph": self.throughput_tph, "additive_dose_fraction": self.additive_dose_fraction}

    @classmethod
    def from_dict(cls, raw: dict) -> "PlanStep":
        return cls(raw["time_hours"], dict(raw.get("controls", {})), dict(raw.get("recipe", {})),
                   raw.get("throughput_tph", 0.0), raw.get("additive_dose_fraction", 0.0))


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
    applicability: str = "unknown"

    def __post_init__(self):
        object.__setattr__(self, "qualities",
                           {name: _clean_number(self.qualities.get(name), f"TrajectoryPoint.{name}")
                            for name in QUALITIES})
        object.__setattr__(self, "severity_proxy", _clean_number(self.severity_proxy, "TrajectoryPoint.severity_proxy"))
        negative = [k for k, v in self.inventories.items() if v < -1e-9]
        if negative:
            raise ContractError(f"TrajectoryPoint[{self.time_hours} ч]: отрицательные остатки {negative}")

    def unknown_qualities(self) -> list[str]:
        return [name for name, value in self.qualities.items() if value is None]

    def to_dict(self) -> dict:
        return {"time_hours": self.time_hours, "qualities": dict(self.qualities),
                "inventories": dict(self.inventories), "production_tph": self.production_tph,
                "cost_proxy": self.cost_proxy, "severity_proxy": self.severity_proxy,
                "applicability": self.applicability}

    @classmethod
    def from_dict(cls, raw: dict) -> "TrajectoryPoint":
        return cls(raw["time_hours"], dict(raw["qualities"]), dict(raw["inventories"]),
                   raw.get("production_tph", 0.0), raw.get("cost_proxy", 0.0),
                   raw.get("severity_proxy"), raw.get("applicability", "unknown"))


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
