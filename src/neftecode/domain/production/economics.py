"""Cost, production and how hard the hydrotreater is being pushed.

Three separate things, deliberately not fused into one score:

* **production** — tonnes of blended product over the plan;
* **cost** — components, the additive and the energy of treating, each from a declared price;
* **severity** — how far the hydrotreater is driven from its reference regime.

Severity is a described index, not a residual life and not a failure probability. The package
contains no catalyst change dates, no run-length and no failure labels, so any claim about
remaining life would be invented. The index only says "this regime is harder than that one",
by rules written down here and weighted by the scenario.

Costs are counted once. Per-tonne prices and totals over the horizon are reported separately,
so a reader cannot accidentally add the same expense twice.
"""
from dataclasses import dataclass
import math

from neftecode.domain.production.scenario import Scenario

#: Contributions the severity index is built from. Every one is observable in the scenario.
SEVERITY_TERMS = ("temperature_above_reference", "throughput_above_reference")


class EconomicsError(ValueError):
    """Raised when a cost or severity input is missing or impossible."""


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


@dataclass(frozen=True)
class StepCost:
    """Cost of one step, split so that nothing is counted twice."""

    hours: float
    production_t: float
    component_cost: float
    additive_cost: float
    treating_cost: float

    @property
    def total(self) -> float:
        return self.component_cost + self.additive_cost + self.treating_cost

    @property
    def per_tonne(self) -> float | None:
        return self.total / self.production_t if self.production_t > 0 else None

    def to_dict(self) -> dict:
        return {"hours": self.hours, "production_t": self.production_t,
                "component_cost": self.component_cost, "additive_cost": self.additive_cost,
                "treating_cost": self.treating_cost, "total_cost": self.total,
                "cost_per_tonne": self.per_tonne}


@dataclass
class Economics:
    """Prices and the severity index, all taken from the scenario."""

    scenario: Scenario

    def price_per_tonne(self, tank_id: str) -> float:
        return self.scenario.tank(tank_id).cost_per_t.value

    def step_cost(self, recipe: dict[str, float], throughput_tph: float, hours: float,
                  additive_dose: float = 0.0,
                  ht_temp_c: float | None = None) -> StepCost:
        """Cost of running `recipe` at `throughput_tph` for `hours`.

        Component cost uses the mass actually drawn. Treating cost is charged on the same
        mass once: a reference part plus a part proportional to how far above the reference
        temperature the reactor is held.
        """
        for name, value in (("throughput_tph", throughput_tph), ("hours", hours),
                            ("additive_dose", additive_dose)):
            if not _finite(value) or value < 0:
                raise EconomicsError(f"{name}: значение должно быть конечным и неотрицательным")
        mass = throughput_tph * hours
        component = sum(self.price_per_tonne(tank_id) * mass * fraction
                        for tank_id, fraction in recipe.items() if fraction > 1e-12)
        additive_mass = mass * additive_dose
        additive_price = (self.scenario.additive.price_per_t.value
                          if self.scenario.additive is not None else 0.0)
        additive = additive_mass * additive_price
        economics = self.scenario.economics
        reference_temp = self.scenario.stages["hydrotreating"].model.get("reference_temp_c")
        if ht_temp_c is None or reference_temp is None:
            extra_degrees = 0.0
        else:
            extra_degrees = max(0.0, ht_temp_c - reference_temp)
        treating = mass * (economics["treating_cost_per_t_at_reference"].value
                           + economics["treating_cost_per_extra_degree_per_t"].value * extra_degrees)
        return StepCost(float(hours), mass, component, additive, treating)

    def severity(self, controls: dict[str, float]) -> dict:
        """Index of how hard the hydrotreater is driven, with every term shown separately.

        Explicitly NOT: catalyst age, remaining life, or a probability of failure. The package
        has no data that would support any of those.
        """
        stage = self.scenario.stages["hydrotreating"]
        model = stage.model or {}
        reference_temp = model.get("reference_temp_c")
        reference_flow = model.get("reference_space_velocity_m3h")
        if reference_temp is None or reference_flow is None:
            return {"available": False, "index": None,
                    "reason": "В сценарии нет опорной точки гидроочистки: тяжесть режима не считается"}
        temp = controls.get("ht_reactor_inlet_temp_c")
        flow = controls.get("ht_feed_flow_m3h")
        if not _finite(temp) or not _finite(flow):
            return {"available": False, "index": None,
                    "reason": "Уставки гидроочистки неизвестны: тяжесть режима не считается"}
        low, high = stage.control_range("ht_reactor_inlet_temp_c")
        flow_low, flow_high = stage.control_range("ht_feed_flow_m3h")
        # Each term is the share of the allowed span already used beyond the reference point.
        temp_span = max(1e-9, high - reference_temp)
        flow_span = max(1e-9, flow_high - reference_flow)
        terms = {
            "temperature_above_reference": max(0.0, temp - reference_temp) / temp_span,
            "throughput_above_reference": max(0.0, flow - reference_flow) / flow_span,
        }
        weights = (self.scenario.policy or {}).get("severity_weights") or {
            "temperature_above_reference": 0.7, "throughput_above_reference": 0.3}
        unknown = set(weights) - set(SEVERITY_TERMS)
        if unknown:
            raise EconomicsError(f"policy.severity_weights: неизвестные слагаемые {', '.join(sorted(unknown))}")
        index = sum(weights.get(name, 0.0) * value for name, value in terms.items())
        return {
            "available": True, "index": float(index), "terms": terms, "weights": dict(weights),
            "reference_temp_c": reference_temp, "reference_flow_m3h": reference_flow,
            "control_range_c": [low, high],
            "reason": "Показатель тяжести режима собран из наблюдаемых слагаемых с явными весами.",
            "scope": "Это описанный индекс режима, а не возраст катализатора, не остаточный ресурс "
                     "и не вероятность отказа: дат замен, наработки и разметки отказов в пакете нет.",
        }

    def summarise(self, steps) -> dict:
        """Totals over a plan. `steps` are the StepCost objects of each step."""
        total = sum(step.total for step in steps)
        production = sum(step.production_t for step in steps)
        return {
            "production_t": production,
            "total_cost": total,
            "cost_per_tonne": total / production if production > 0 else None,
            "component_cost": sum(step.component_cost for step in steps),
            "additive_cost": sum(step.additive_cost for step in steps),
            "treating_cost": sum(step.treating_cost for step in steps),
            "steps": [step.to_dict() for step in steps],
            "rule": "Стоимость за горизонт — сумма по шагам; стоимость на тонну получается делением "
                    "на выпуск. Один и тот же расход не входит в сумму дважды.",
            "scope": "Условные единицы сценария. Это не тарифы завода и не измеренная экономия.",
        }
