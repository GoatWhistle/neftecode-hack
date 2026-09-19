from dataclasses import dataclass, field

from neftecode.domain.shared.primitives import ContractError, CONFIRMED_SCOPE, SCENARIO_SCOPE, _finite


@dataclass(frozen=True)
class PlanStep:

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
