from collections.abc import Callable
from dataclasses import dataclass, replace
import copy
import math

from neftecode.application.progress import reporting_to
from neftecode.application.use_cases.make_decision import MakeDecision
from neftecode.domain.advisory.optimizer import DEFAULT_BUDGET
from neftecode.domain.production.scenario import Scenario

SULFUR_ABSOLUTE_MGKG = 1.0
INVENTORY_RELATIVE = 0.25
MAIN_TANK = "main"

MEASURED_SOURCES = ("derived", "measured")

NOT_MEASURED_NOTE = ("В выданных данных нет прямой пробы содержимого резервуара: рабочая оценка получена по "
                     "доверенным показаниям притока за окно обновления при допущении полного перемешивания. "
                     "На заводе для паспортизации анализируют пробу из резервуара.")

STABLE_VERDICT = ("Решение не меняется при ошибке оценки резервуара в заявленных пределах: "
                  "статус и выбранный план те же.")

SENSITIVE_VERDICT = ("Решение зависит от оценки, которую мы не измеряли: при ошибке начальной оценки "
                     "резервуара в заявленных пределах рекомендация меняется. Состояние резервуара "
                     "стоит уточнить прямой пробой до исполнения.")

UNAVAILABLE_NOTE = "Проверка чувствительности к оценке резервуара не выполнена"


class TankEstimateError(ValueError):
    pass


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def main_tank(raw: dict) -> dict | None:
    for tank in raw.get("tanks") or []:
        if tank.get("tank_id") == MAIN_TANK:
            return tank
    return None


def estimate_provenance(raw: dict) -> dict:
    tank = main_tank(raw)
    if tank is None:
        return {"tank_id": MAIN_TANK, "available": False, "reason": "Главный резервуар не описан в сценарии"}
    sulfur = (tank.get("properties") or {}).get("sulfur_mgkg") or {}
    inventory = tank.get("inventory") or {}
    return {"tank_id": MAIN_TANK, "available": _finite(sulfur.get("value")) and _finite(inventory.get("value")),
            "sulfur_mgkg": sulfur.get("value"), "sulfur_source": sulfur.get("source"),
            "inventory_t": inventory.get("value"), "inventory_source": inventory.get("source"),
            "from_estimate": sulfur.get("source") in MEASURED_SOURCES,
            "sulfur_note": sulfur.get("note"), "reason": None}


def perturbations(raw: dict, sulfur_delta: float = SULFUR_ABSOLUTE_MGKG,
                  inventory_share: float = INVENTORY_RELATIVE) -> tuple[dict, ...]:
    origin = estimate_provenance(raw)
    if not origin["available"]:
        return ()
    sulfur, inventory = float(origin["sulfur_mgkg"]), float(origin["inventory_t"])
    out = []
    for sign, word in ((1.0, "выше"), (-1.0, "ниже")):
        value = sulfur + sign * sulfur_delta
        if value > 0:
            out.append({"name": f"сера резервуара на {sulfur_delta:g} мг/кг {word} оценки",
                        "field": "sulfur_mgkg", "value": value, "estimate": sulfur})
    for sign, word in ((1.0, "больше"), (-1.0, "меньше")):
        value = inventory * (1.0 + sign * inventory_share)
        if value > 0:
            out.append({"name": f"запас резервуара на {inventory_share:.0%} {word} оценки",
                        "field": "inventory", "value": value, "estimate": inventory})
    return tuple(out)


def apply(raw: dict, spec: dict) -> dict:
    out = copy.deepcopy(raw)
    tank = main_tank(out)
    if tank is None:
        raise TankEstimateError("Главный резервуар не описан в сценарии")
    if not _finite(spec.get("value")) or spec["value"] <= 0:
        raise TankEstimateError(f"{spec.get('name')}: значение должно быть конечным и положительным")
    if spec["field"] == "inventory":
        tank["inventory"]["value"] = float(spec["value"])
    elif spec["field"] == "sulfur_mgkg":
        tank["properties"]["sulfur_mgkg"] = {**(tank["properties"].get("sulfur_mgkg") or {}),
                                             "value": float(spec["value"])}
    else:
        raise TankEstimateError(f"{spec.get('name')}: неизвестное поле {spec['field']}")
    return out


def apply_to_tanks(initial_tanks, spec: dict):
    if initial_tanks is None or MAIN_TANK not in initial_tanks:
        return initial_tanks
    stocks = dict(initial_tanks)
    tank = stocks[MAIN_TANK]
    if spec["field"] == "inventory":
        stocks[MAIN_TANK] = replace(tank, inventory_t=float(spec["value"]))
    else:
        stocks[MAIN_TANK] = replace(tank, properties={**tank.properties,
                                                      "sulfur_mgkg": float(spec["value"])})
    return stocks


@dataclass
class TankEstimateCheck:

    scenario: Scenario
    raw: dict
    scenario_parser: Callable[[dict], Scenario] | None = None
    decision_factory: Callable[[Scenario], object] | None = None
    sulfur_delta: float = SULFUR_ABSOLUTE_MGKG
    inventory_share: float = INVENTORY_RELATIVE

    def evaluate(self, status: str, plan_id: str | None, budget: int = DEFAULT_BUDGET, confirmed=(),
                 current_operation: dict | None = None, initial_tanks=None) -> dict:
        if self.scenario_parser is None or self.decision_factory is None:
            return self._unavailable("нет парсера сценария или фабрики решения")
        origin = estimate_provenance(self.raw)
        if not origin["available"]:
            return self._unavailable(origin.get("reason") or "оценка резервуара в сценарии не задана")
        specs = perturbations(self.raw, self.sulfur_delta, self.inventory_share)
        if not specs:
            return self._unavailable("допустимых возмущений оценки резервуара не построено")
        results = [self._one(spec, status, plan_id, budget, confirmed, current_operation, initial_tanks)
                   for spec in specs]
        return self._report(origin, results, status, plan_id)

    def _one(self, spec: dict, status: str, plan_id: str | None, budget: int, confirmed,
             current_operation: dict | None, initial_tanks=None) -> dict:
        entry = {"perturbation": spec["name"], "field": spec["field"], "estimate": spec["estimate"],
                 "value": spec["value"]}
        try:
            altered_raw = apply(self.raw, spec)
            altered = self.scenario_parser(altered_raw)
            with reporting_to(None):
                decision = self.decision_factory(altered).decide(
                    budget=budget, confirmed=confirmed, raw_scenario=altered_raw,
                    current_operation=current_operation, initial_tanks=apply_to_tanks(initial_tanks, spec))
        except (TankEstimateError, ValueError, KeyError) as exc:
            return {**entry, "outcome": "not_evaluable", "reason": str(exc)[:200]}
        altered_plan = (decision.get("selected_plan") or {}).get("plan_id")
        same = decision["status"] == status and altered_plan == plan_id
        return {**entry, "outcome": "same" if same else "changed", "status": decision["status"],
                "plan_id": altered_plan, "reason": str(decision.get("reason"))[:200],
                "cost_per_tonne": decision.get("cost_per_tonne"),
                "production_t": decision.get("production_t"),
                "immediate_action": decision.get("immediate_action")}

    def _report(self, origin: dict, results: list[dict], status: str, plan_id: str | None) -> dict:
        evaluated = [r for r in results if r["outcome"] in ("same", "changed")]
        changed = [r for r in evaluated if r["outcome"] == "changed"]
        sensitive = bool(changed)
        return {"available": True, "tank_id": MAIN_TANK, "baseline_status": status, "baseline_plan": plan_id,
                "sulfur_estimate_mgkg": origin["sulfur_mgkg"], "sulfur_delta_mgkg": self.sulfur_delta,
                "inventory_estimate_t": origin["inventory_t"], "inventory_share": self.inventory_share,
                "estimate_is_derived": origin["from_estimate"],
                "perturbations_declared": len(results), "perturbations_evaluated": len(evaluated),
                "same": len(evaluated) - len(changed), "changed": len(changed), "sensitive": sensitive,
                "results": results,
                "verdict": SENSITIVE_VERDICT if sensitive else STABLE_VERDICT,
                "limits": [NOT_MEASURED_NOTE,
                           f"Проверены только две величины: сера ±{self.sulfur_delta:g} мг/кг и запас "
                           f"±{self.inventory_share:.0%}. Пределы выбраны нами, это не доверительный интервал.",
                           "Возмущается начальное состояние резервуара; прогноз притока и модель отклика "
                           "проверяются отдельно проверкой устойчивости.",
                           "Каждое возмущение прогоняется полным поиском заново, поэтому смена плана "
                           "может означать и смену действия, и равноценную замену внутри того же действия."]}

    @staticmethod
    def _unavailable(reason: str) -> dict:
        return {"available": False, "reason": f"{UNAVAILABLE_NOTE}: {reason}", "sensitive": False,
                "tank_id": MAIN_TANK}


def plain_decision(scenario: Scenario) -> MakeDecision:
    return MakeDecision(scenario)


def default_tank_estimate_factory(scenario: Scenario, raw: dict,
                                  scenario_parser: Callable[[dict], Scenario]):
    if scenario.tank_park is not None:
        from neftecode.application.services.park_phase import ParkPhaseCheck
        return ParkPhaseCheck(scenario, dict(raw), scenario_parser, plain_decision)
    return TankEstimateCheck(scenario, dict(raw), scenario_parser=scenario_parser,
                             decision_factory=plain_decision)
