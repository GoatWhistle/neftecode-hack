from dataclasses import dataclass, field

from neftecode.domain.shared.primitives import ContractError, QUALITIES, SCENARIO_SCOPE, _clean_number


@dataclass(frozen=True)
class TrajectoryPoint:

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
