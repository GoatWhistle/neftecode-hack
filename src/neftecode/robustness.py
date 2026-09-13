"""Would the chosen plan still hold if the models are a little wrong?

The models here are ours: scenario coefficients, a declared response lag, component properties
taken from the scenario rather than measured. A plan that only works when all of that is exactly
right is not a plan, it is a coincidence. So the selected plan is re-evaluated under a declared
set of perturbations and the result says plainly how many of them it survives.

Deliberate limits of this check:

* the perturbations are OURS. Surviving them is not a probability of success and not a
  confidence interval; it is "this plan held under these listed deviations".
* the same response model is perturbed, so this does not test a structurally different plant.
  That limitation is reported with the result rather than left for the reader to notice.
* a long excursion in the history is not evidence of a new regime. Applicability is decided by
  the model's declared region, not by how unusual a period looked.
"""
from dataclasses import dataclass, field, replace
import copy
import json
import math

from .planner import Planner
from neftecode.scenario import Scenario, parse_scenario

#: Deviations applied one at a time. Each is a named, reproducible edit of the scenario.
DEFAULT_PERTURBATIONS = (
    {"name": "сера сырья +10%", "path": "crude.sulfur_wt_pct", "factor": 1.10},
    {"name": "сера сырья -10%", "path": "crude.sulfur_wt_pct", "factor": 0.90},
    {"name": "отклик ГО слабее на 20%", "path": "hydrotreating.conversion_per_degree", "factor": 0.80},
    {"name": "запаздывание отклика +50%", "path": "hydrotreating.response_lag_hours", "factor": 1.50},
    {"name": "сера резерва +50%", "path": "tank.reserve.sulfur_mgkg", "factor": 1.50},
    {"name": "сера основного компонента +10%", "path": "tank.main.sulfur_mgkg", "factor": 1.10},
    {"name": "запас резерва -20%", "path": "tank.reserve.inventory", "factor": 0.80},
    {"name": "доля серы в дизельной фракции +10%", "path": "avt.sulfur_partition", "factor": 1.10},
)

#: A plan surviving fewer than this share of the perturbations is called fragile.
FRAGILE_BELOW = 1.0


class RobustnessError(ValueError):
    """Raised when a perturbation cannot be applied to the scenario as declared."""


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def perturb(raw: dict, spec: dict) -> dict:
    """Apply one named perturbation to a raw scenario document."""
    out = copy.deepcopy(raw)
    path, factor = spec["path"], spec["factor"]
    if not _finite(factor) or factor <= 0:
        raise RobustnessError(f"{spec['name']}: множитель должен быть конечным и положительным")
    if path.startswith("crude."):
        key = path.split(".", 1)[1]
        out["crude"][key]["value"] *= factor
    elif path.startswith("tank."):
        _, tank_id, field_name = path.split(".", 2)
        for tank in out["tanks"]:
            if tank["tank_id"] != tank_id:
                continue
            if field_name == "inventory":
                tank["inventory"]["value"] *= factor
            else:
                if tank["properties"].get(field_name) is None:
                    raise RobustnessError(f"{spec['name']}: у {tank_id} нет свойства {field_name}")
                tank["properties"][field_name]["value"] *= factor
            break
        else:
            raise RobustnessError(f"{spec['name']}: резервуар {tank_id} не описан")
    elif path.startswith("hydrotreating."):
        key = path.split(".", 1)[1]
        stage = out["stages"]["hydrotreating"]
        if key == "response_lag_hours":
            # The case bounds the lag at three hours; a perturbation may not step outside them.
            stage[key]["value"] = min(3.0, stage[key]["value"] * factor)
        else:
            stage["model"][key] *= factor
    elif path.startswith("avt."):
        key = path.split(".", 1)[1]
        out["stages"]["avt"]["model"][key] *= factor
    else:
        raise RobustnessError(f"{spec['name']}: неизвестный путь {path}")
    return out


@dataclass
class RobustnessCheck:
    """Re-evaluates one plan across the declared perturbations."""

    scenario: Scenario
    raw: dict
    perturbations: tuple = DEFAULT_PERTURBATIONS

    def run(self, plan, confirmed=(), initial_tanks=None, current_operation=None) -> dict:
        """Evaluate `plan` under each perturbation. Reports every outcome, good and bad."""
        results = []
        for spec in self.perturbations:
            try:
                altered = parse_scenario(perturb(self.raw, spec))
            except (RobustnessError, ValueError) as exc:
                results.append({"perturbation": spec["name"], "outcome": "not_applicable",
                                "reason": str(exc)})
                continue
            planner = Planner(altered)
            try:
                stocks = initial_tanks
                if stocks is not None and spec["path"].startswith("tank."):
                    _, tank_id, attribute = spec["path"].split(".", 2)
                    stocks = dict(stocks)
                    tank = stocks[tank_id]
                    if attribute == "inventory":
                        stocks[tank_id] = replace(tank, inventory_t=tank.inventory_t * spec["factor"])
                    elif tank.properties.get(attribute) is not None:
                        stocks[tank_id] = replace(tank, properties={**tank.properties,
                            attribute: tank.properties[attribute] * spec["factor"]})
                evaluation = planner.evaluate(plan, confirmed, initial_tanks=stocks,
                                              current_operation=current_operation)
            except ValueError as exc:
                results.append({"perturbation": spec["name"], "outcome": "not_evaluable",
                                "reason": str(exc)})
                continue
            first = evaluation.gate.first_violation
            results.append({
                "perturbation": spec["name"], "path": spec["path"], "factor": spec["factor"],
                "outcome": "holds" if evaluation.feasible else "violated",
                "first_violation": None if first is None else
                                   {"constraint_id": first.constraint_id,
                                    "time_hours": first.time_hours, "reason": first.reason},
                "unknown_requirements": [c.constraint_id for c in evaluation.gate.unknown_requirements()],
                "production_t": evaluation.production_t,
                "cost_per_tonne": evaluation.cost_per_tonne})
        evaluated = [r for r in results if r["outcome"] in ("holds", "violated")]
        held = [r for r in evaluated if r["outcome"] == "holds"]
        share = len(held) / len(evaluated) if evaluated else None
        fragile = share is not None and share < FRAGILE_BELOW
        return {
            "plan_id": getattr(plan, "plan_id", None),
            "perturbations_declared": len(self.perturbations),
            "perturbations_evaluated": len(evaluated),
            "held": len(held),
            "violated": len(evaluated) - len(held),
            "share_holding": share,
            "fragile": fragile,
            "results": results,
            "verdict": ("План сохраняет допустимость при всех перечисленных отклонениях"
                        if not fragile else
                        "План теряет допустимость при допустимом отклонении: как надёжный не выдаётся"),
            "limits": [
                "Возмущения выбраны нами и перечислены поимённо; доля выдержанных — не вероятность "
                "успеха и не доверительный интервал.",
                "Проверка идёт на той же модели отклика, которой пользуется оптимизатор, поэтому "
                "структурно иная установка ею не проверена.",
                "Длительный исторический эпизод сам по себе новым режимом не признаётся: "
                "применимость определяется объявленной областью модели.",
            ],
        }


def choose_robust(evaluations, checks: dict[str, dict]) -> dict:
    """Prefer a plan that survives the perturbations over a nominally better fragile one."""
    feasible = [e for e in evaluations if e.feasible]
    if not feasible:
        return {"selected": None, "reason": "Допустимых планов нет"}
    robust = [e for e in feasible if not checks.get(e.candidate.candidate_id, {}).get("fragile", True)]
    if robust:
        best = min(robust, key=lambda e: e.key())
        return {"selected": best.candidate.candidate_id,
                "reason": "Выбран план, сохраняющий допустимость при заданных отклонениях",
                "fragile_alternatives": [e.candidate.candidate_id for e in feasible if e not in robust][:5]}
    best = min(feasible, key=lambda e: e.key())
    return {"selected": best.candidate.candidate_id,
            "reason": "Все допустимые планы хрупки при заданных отклонениях: результат выдаётся "
                      "с этим предупреждением, а не как надёжный",
            "fragile": True}
