from collections.abc import Callable
from dataclasses import dataclass, replace
import copy
import math

from neftecode.application.use_cases.plan_operation import PlanOperation
from neftecode.domain.advisory.response_guard import moves_hydrotreating, moves_temperature
from neftecode.domain.production.scenario import Scenario
from neftecode.evaluation.tank_estimate import TankEstimateCheck, default_tank_estimate_factory

# Совместный стресс отклика обязателен во всех сценариях, а не только там, где сценарий
# перечислил его в policy.mandatory_robustness_paths. План, который держится лишь при
# номинальном отклике и номинальной задержке, как надёжный не выдаётся: слабый отклик и
# увеличенная задержка приходят вместе, и это самый вероятный совместный промах модели.
# Объект один и входит в поставляемый набор — признак mandatory нельзя потерять копией.
COMBINED_RESPONSE_STRESS = {
    "name": "слабый отклик ГО и задержка +50% одновременно",
    "path": "hydrotreating.response_stress", "factor": 1.0, "mandatory": True,
}

DEFAULT_PERTURBATIONS = (
    {"name": "сера сырья +10%", "path": "crude.sulfur_wt_pct", "factor": 1.10},
    {"name": "сера сырья -10%", "path": "crude.sulfur_wt_pct", "factor": 0.90},
    {"name": "отклик ГО слабее на 20%", "path": "hydrotreating.conversion_per_degree", "factor": 0.80},
    {"name": "запаздывание отклика +50%", "path": "hydrotreating.response_lag_hours", "factor": 1.50},
    {"name": "сера резерва +50%", "path": "tank.reserve.sulfur_mgkg", "factor": 1.50},
    {"name": "сера основного компонента +10%", "path": "tank.main.sulfur_mgkg", "factor": 1.10},
    {"name": "подача резерва -20%", "path": "tank.reserve.max_outflow", "factor": 0.80},
    {"name": "доля серы в дизельной фракции +10%", "path": "avt.sulfur_partition", "factor": 1.10},
    COMBINED_RESPONSE_STRESS,
)

FRAGILE_BELOW = 1.0


def response_perturbations(raw: dict) -> tuple:
    model = (((raw.get("stages") or {}).get("hydrotreating") or {}).get("model") or {})
    beta = model.get("beta_mgkg_per_c")
    bounds = model.get("weak_strong") or model.get("beta_ci")
    if model.get("provenance") != "derived" or not _finite(beta) or beta == 0 \
            or not isinstance(bounds, (list, tuple)) or len(bounds) != 2:
        return ()
    out = []
    for label, bound in zip(("слабый", "сильный"), bounds):
        if not _finite(bound) or bound / beta <= 0:
            continue
        out.append({"name": f"отклик ГО по данным: {label} край диапазона β={bound:g}",
                    "path": "hydrotreating.conversion_per_degree", "factor": bound / beta})
    return tuple(out)


def inapplicable_reason(spec: dict, plan, base_controls: dict, pending) -> str | None:
    path = spec.get("path", "")
    if path in ("hydrotreating.conversion_per_degree", "hydrotreating.response_stress") \
            and not moves_temperature(plan, base_controls, pending):
        return "план не меняет температуру входа реактора: возмущение отклика на него не действует"
    if path in ("hydrotreating.response_lag_hours", "hydrotreating.response_stress") \
            and not moves_hydrotreating(plan, base_controls, pending):
        return "план не меняет уставки гидроочистки: возмущение задержки на него не действует"
    return None


class RobustnessError(ValueError):
    pass


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def perturb(raw: dict, spec: dict) -> dict:
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
            if field_name in ("inventory", "max_outflow"):
                if field_name not in tank:
                    raise RobustnessError(f"{spec['name']}: у {tank_id} нет поля {field_name}")
                tank[field_name]["value"] *= factor
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
        if key == "response_stress":
            stage["response_lag_hours"]["value"] = min(3.0, stage["response_lag_hours"]["value"] * 1.50)
            stage["model"]["conversion_per_degree"] *= 0.80
        elif key == "response_lag_hours":
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

    scenario: Scenario
    raw: dict
    perturbations: tuple = DEFAULT_PERTURBATIONS
    scenario_parser: Callable[[dict], Scenario] | None = None
    tank_estimate_factory: Callable[..., TankEstimateCheck | None] = default_tank_estimate_factory

    def run(self, plan, confirmed=(), initial_tanks=None, current_operation=None) -> dict:
        if self.scenario_parser is None:
            raise RobustnessError("Для проверки устойчивости не передан парсер сценария")
        results = []
        specs = tuple(self.perturbations) + response_perturbations(self.raw)
        mandatory_paths = set((self.raw.get("policy") or {}).get("mandatory_robustness_paths") or ())
        base_planner = PlanOperation(self.scenario)
        base_controls = base_planner.base_controls()
        pending = base_planner.confirmed_with_operation(confirmed, current_operation)
        for spec in specs:
            mandatory = bool(spec.get("mandatory", False) or spec.get("path") in mandatory_paths)
            reason = inapplicable_reason(spec, plan, base_controls, pending)
            if reason is not None:
                results.append({"perturbation": spec["name"], "path": spec["path"], "factor": spec["factor"],
                                "mandatory": mandatory,
                                "outcome": "not_applicable", "reason": reason})
                continue
            try:
                altered = self.scenario_parser(perturb(self.raw, spec))
            except (RobustnessError, ValueError) as exc:
                results.append({"perturbation": spec["name"],
                                "mandatory": mandatory,
                                "outcome": "not_applicable",
                                "reason": str(exc)})
                continue
            planner = PlanOperation(altered)
            try:
                stocks = initial_tanks
                if stocks is not None and spec["path"].startswith("tank."):
                    _, tank_id, attribute = spec["path"].split(".", 2)
                    stocks = dict(stocks)
                    tank = stocks[tank_id]
                    if attribute == "inventory":
                        stocks[tank_id] = replace(tank, inventory_t=tank.inventory_t * spec["factor"])
                    elif attribute == "max_outflow":
                        stocks[tank_id] = replace(tank, max_outflow_tph=tank.max_outflow_tph * spec["factor"])
                    elif tank.properties.get(attribute) is not None:
                        stocks[tank_id] = replace(tank, properties={**tank.properties,
                            attribute: tank.properties[attribute] * spec["factor"]})
                evaluation = planner.evaluate(plan, confirmed, initial_tanks=stocks,
                                              current_operation=current_operation)
            except ValueError as exc:
                results.append({"perturbation": spec["name"],
                                "mandatory": mandatory,
                                "outcome": "not_evaluable",
                                "reason": str(exc)})
                continue
            first = evaluation.gate.first_violation
            results.append({
                "perturbation": spec["name"], "path": spec["path"], "factor": spec["factor"],
                "mandatory": mandatory,
                "outcome": "holds" if evaluation.feasible else "violated",
                "first_violation": None if first is None else
                                   {"constraint_id": first.constraint_id,
                                    "time_hours": first.time_hours, "reason": first.reason},
                "unknown_requirements": [c.constraint_id for c in evaluation.gate.unknown_requirements()],
                "production_t": evaluation.production_t,
                "cost_per_tonne": evaluation.cost_per_tonne})
        evaluated = [r for r in results if r["outcome"] in ("holds", "violated")]
        held = [r for r in evaluated if r["outcome"] == "holds"]
        not_applicable = [r for r in results if r["outcome"] == "not_applicable"]
        share = len(held) / len(evaluated) if evaluated else None
        fragile = share is not None and share < FRAGILE_BELOW
        mandatory = [r for r in results if r.get("mandatory")]
        mandatory_evaluated = [r for r in mandatory if r["outcome"] in ("holds", "violated", "not_evaluable")]
        mandatory_failures = [r for r in mandatory_evaluated if r["outcome"] != "holds"]
        return {
            "plan_id": getattr(plan, "plan_id", None),
            "perturbations_declared": len(specs),
            "perturbations_evaluated": len(evaluated),
            "held": len(held),
            "violated": len(evaluated) - len(held),
            "not_applicable": len(not_applicable),
            "share_holding": share,
            "fragile": fragile,
            "mandatory_declared": len(mandatory),
            "mandatory_evaluated": len(mandatory_evaluated),
            "mandatory_failed": len(mandatory_failures),
            "mandatory_failure_names": [r["perturbation"] for r in mandatory_failures],
            "results": results,
            "verdict": ("План сохраняет допустимость при всех перечисленных отклонениях"
                        if not fragile else
                        "План нарушает обязательный диапазон устойчивости: рекомендация блокируется"
                        if mandatory_failures else
                        "План теряет допустимость при допустимом отклонении: как надёжный не выдаётся"),
            "limits": [
                "Возмущения выбраны нами и перечислены поимённо; доля выдержанных — не вероятность "
                "успеха и не доверительный интервал.",
                "Возмущения отклика и задержки, не действующие на план без хода уставок ГО, помечены «неприменимо» "
                "и в долю выдержанных не входят.",
                "Проверка идёт на той же модели отклика, которой пользуется оптимизатор, поэтому "
                "структурно иная установка ею не проверена.",
                "Длительный исторический эпизод сам по себе новым режимом не признаётся: "
                "применимость определяется объявленной областью модели.",
            ],
        }

    def evaluate(self, scenario, raw_scenario, plan, confirmed=(), initial_tanks=None,
                 current_operation=None) -> dict:
        return type(self)(scenario, raw_scenario, self.perturbations, self.scenario_parser,
                          self.tank_estimate_factory).run(
            plan, confirmed, initial_tanks=initial_tanks, current_operation=current_operation)


def choose_robust(evaluations, checks: dict[str, dict]) -> dict:
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
