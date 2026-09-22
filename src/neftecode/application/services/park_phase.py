from collections.abc import Callable
from dataclasses import dataclass
import copy

from neftecode.application.progress import reporting_to
from neftecode.domain.advisory.optimizer import DEFAULT_BUDGET
from neftecode.domain.production.park import capacity_tonnes
from neftecode.domain.production.scenario import Scenario


@dataclass
class ParkPhaseCheck:
    """Проверяет решение при неизвестном времени τ с начала текущего налива."""

    scenario: Scenario
    raw: dict
    scenario_parser: Callable[[dict], Scenario]
    decision_factory: Callable[[Scenario], object]

    def evaluate(self, status: str, plan_id: str | None, budget: int = DEFAULT_BUDGET, confirmed=(),
                 current_operation: dict | None = None, initial_tanks=None) -> dict:
        config = self.scenario.tank_park
        if config is None:
            return {"available": False, "sensitive": False, "mode": "park_phase",
                    "reason": "Парк резервуаров в сценарии не описан"}
        tank = self.scenario.tank(config.component_tank_id)
        if tank.inflow.value <= 0:
            return {"available": False, "sensitive": True, "mode": "park_phase",
                    "reason": "Для перебора фазы нужен положительный приток"}
        if config.source == "scenario" and not self.raw.get("measurement_binding"):
            return {
                "available": True, "sensitive": False, "changed": 0,
                "mode": "park_phase", "tank_id": config.component_tank_id,
                "baseline_status": status, "baseline_plan": plan_id,
                "phase_source": "scenario", "phase_offsets_h": list(config.phase_offsets_h),
                "perturbations_declared": 0, "perturbations_evaluated": 0,
                "same": 0, "results": [],
                "verdict": "Начальные стадии заданы синтетическим сценарием; перебор τ не требуется.",
                "limits": ["Стадии являются допущением сценария и не выданы за измерение завода."],
            }
        fill_h = capacity_tonnes(config.capacity_m3, config.density_kgm3) / tank.inflow.value
        taus = tuple(dict.fromkeys((0.0, fill_h / 2.0, max(0.0, fill_h - 0.5))))
        results = [self._one(tau, fill_h, status, plan_id, budget, confirmed,
                             current_operation, initial_tanks) for tau in taus]
        evaluated = [item for item in results if item["outcome"] in ("same", "changed")]
        changed = [item for item in evaluated if item["outcome"] == "changed"]
        unavailable = [item for item in results if item["outcome"] == "not_evaluable"]
        sensitive = bool(changed or unavailable)
        failed_taus = [item["tau_h"] for item in changed + unavailable]
        verdict = (
            "Совет зависит от стадии резервуаров, нужен фактический уровень; "
            f"неустойчивые τ: {', '.join(f'{value:.3g} ч' for value in failed_taus)}."
            if sensitive else
            "Статус и выбранный план одинаковы для трёх контрольных фаз парка."
        )
        return {
            "available": not unavailable,
            "sensitive": sensitive,
            "changed": len(changed),
            "mode": "park_phase",
            "tank_id": config.component_tank_id,
            "baseline_status": status,
            "baseline_plan": plan_id,
            "fill_duration_h": fill_h,
            "taus_h": list(taus),
            "failed_taus_h": failed_taus,
            "perturbations_declared": len(results),
            "perturbations_evaluated": len(evaluated),
            "same": len(evaluated) - len(changed),
            "results": results,
            "verdict": verdict,
            "limits": [
                "τ — модельное время с начала налива; фактический тег уровня не передан.",
                "Стадии остальных резервуаров следуют из интервала между началами наливов.",
                "Проверка сравнивает статус и plan_id после полного повторного поиска.",
            ],
        }

    def _one(self, tau: float, fill_h: float, status: str, plan_id: str | None,
             budget: int, confirmed, current_operation, initial_tanks) -> dict:
        entry = {"tau_h": tau}
        try:
            raw = copy.deepcopy(self.raw)
            park = raw["tank_park"]
            count = int(park["tank_count"])
            cycle_h = count * fill_h
            park["phase_offsets_h"] = [round((tau + index * fill_h) % cycle_h, 9)
                                       for index in range(count)]
            park["source"] = "derived"
            scenario = self.scenario_parser(raw)
            with reporting_to(None):
                decision = self.decision_factory(scenario).decide(
                    budget=budget, confirmed=confirmed, raw_scenario=raw,
                    current_operation=current_operation, initial_tanks=initial_tanks)
        except (KeyError, TypeError, ValueError) as exc:
            return {**entry, "outcome": "not_evaluable", "reason": str(exc)[:200]}
        altered_plan = (decision.get("selected_plan") or {}).get("plan_id")
        same = decision.get("status") == status and altered_plan == plan_id
        return {**entry, "outcome": "same" if same else "changed",
                "status": decision.get("status"), "plan_id": altered_plan,
                "reason": str(decision.get("reason"))[:200]}
