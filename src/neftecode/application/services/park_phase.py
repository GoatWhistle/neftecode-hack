from collections.abc import Callable
from dataclasses import dataclass
import copy

from neftecode.application.progress import reporting_to
from neftecode.application.cancellation import check_cancelled
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

    def evaluate_candidates(self, plans: dict, validate: Callable, certify: Callable | None = None) -> dict | None:
        """Проверяет содержание каждого переданного плана, не победителей новых поисков."""
        config = self.scenario.tank_park
        if config is None or (config.source == "scenario" and not self.raw.get("measurement_binding")):
            return None
        tank = self.scenario.tank(config.component_tank_id)
        if tank.inflow.value <= 0:
            return {"allowed_ids": [], "checks": {}, "coverage": {}, "taus_h": [], "available": False,
                    "errors": ["Для проверки фаз нужен положительный приток"], "unavailable_taus_h": []}
        fill_h = capacity_tonnes(config.capacity_m3, config.density_kgm3) / tank.inflow.value
        taus = tuple(dict.fromkeys((0.0, fill_h / 2.0, max(0.0, fill_h - 0.5))))
        phases = []
        errors = []
        unavailable_taus = []
        for tau in taus:
            check_cancelled()
            try:
                raw = copy.deepcopy(self.raw)
                park = raw["tank_park"]
                count = int(park["tank_count"])
                park["phase_offsets_h"] = [(tau + i * fill_h) % (count * fill_h) for i in range(count)]
                park["source"] = "derived"
                phases.append((tau, self.scenario_parser(raw), raw))
            except (KeyError, TypeError, ValueError) as exc:
                errors.append(f"τ={tau:g} ч: {exc}")
                unavailable_taus.append(tau)
        checks, coverage = {}, {}
        for plan_id, plan in plans.items():
            try:
                coverage[plan_id] = (certify(plan) if certify is not None else
                                     {"complete": False, "reasons": ["Непрерывная проверка фаз не передана"]})
            except (KeyError, TypeError, ValueError) as exc:
                coverage[plan_id] = {"complete": False, "reasons": [str(exc)[:200]]}
            rows = []
            for tau, scenario, raw in phases:
                check_cancelled()
                try:
                    with reporting_to(None):
                        result = validate(scenario, raw, plan)
                    rows.append({"tau_h": tau, "plan_id": plan_id, **result})
                except (KeyError, TypeError, ValueError) as exc:
                    rows.append({"tau_h": tau, "plan_id": plan_id, "feasible": False,
                                 "outcome": "not_evaluable", "reasons": [str(exc)[:200]]})
            checks[plan_id] = rows
        allowed = [plan_id for plan_id, rows in checks.items()
                   if not errors and coverage[plan_id]["complete"]
                   and len(rows) == len(taus) and all(row["feasible"] for row in rows)]
        return {"available": not errors and all(row["outcome"] != "not_evaluable"
                                                for rows in checks.values() for row in rows),
                "allowed_ids": allowed, "checks": checks, "coverage": coverage, "taus_h": list(taus),
                "fill_duration_h": fill_h, "errors": errors, "unavailable_taus_h": unavailable_taus}

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
        try:
            maker = self._maker(self.scenario, self.raw)
            plans, _ = maker.build_plans(budget, current_operation)
            plan = next((p for p in plans if p.plan_id == plan_id), None)
            coverage = (maker._phase_certificate(plan, self.raw, confirmed, initial_tanks, current_operation)
                        if plan is not None else {"complete": False, "reasons": ["Содержание плана не найдено"]})
        except (KeyError, TypeError, ValueError) as exc:
            coverage = {"complete": False, "reasons": [str(exc)[:200]]}
        evaluated = [item for item in results if item["outcome"] in ("same", "changed")]
        changed = [item for item in evaluated if item["outcome"] == "changed"]
        unavailable = [item for item in results if item["outcome"] == "not_evaluable"]
        sensitive = bool(changed or unavailable or not coverage["complete"])
        failed_taus = [item["tau_h"] for item in changed + unavailable]
        verdict = (
            "План не подтверждён на всём интервале стадий резервуаров; нужен фактический уровень. "
            + (f"Неустойчивые τ: {', '.join(f'{value:.3g} ч' for value in failed_taus)}. " if failed_taus else "")
            + "; ".join(coverage["reasons"])
            if sensitive else
            "Выбранный план подтверждён на всём непрерывном интервале фаз парка."
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
            "coverage": coverage,
            "verdict": verdict,
            "limits": [
                "τ — модельное время с начала налива; фактический тег уровня не передан.",
                "Стадии остальных резервуаров следуют из интервала между началами наливов.",
                "Один и тот же план проверяется во всех фазах; новые победители не сравниваются.",
                "Непрерывные границы по τ дополняют Gate на временной сетке горизонта; "
                "прямые прогоны в трёх точках служат диагностикой.",
            ],
        }

    def _one(self, tau: float, fill_h: float, status: str, plan_id: str | None,
             budget: int, confirmed, current_operation, initial_tanks) -> dict:
        entry = {"tau_h": tau}
        try:
            plans, _ = self.decision_factory(self.scenario).build_plans(budget, current_operation)
            plan = next((p for p in plans if p.plan_id == plan_id), None)
            if plan is None:
                return {**entry, "outcome": "not_evaluable", "reason": "Содержание плана не найдено"}
            raw = copy.deepcopy(self.raw)
            park = raw["tank_park"]
            count = int(park["tank_count"])
            cycle_h = count * fill_h
            park["phase_offsets_h"] = [(tau + index * fill_h) % cycle_h
                                       for index in range(count)]
            park["source"] = "derived"
            scenario = self.scenario_parser(raw)
            maker = self._maker(scenario, raw)
            with reporting_to(None):
                evaluation = maker.evaluate_plan(plan, confirmed, initial_tanks, current_operation)
                if not maker.passes_review(evaluation):
                    return {**entry, "outcome": "changed", "status": "refuse", "plan_id": plan_id,
                            "reason": "; ".join(evaluation.gate.rejection_reasons())[:200]}
                decision = maker.release(
                    {"selected": evaluation.to_dict(), "reason": "Проверка заданного плана"},
                    plan, [evaluation], {plan_id: plan}, [], budget=budget, confirmed=confirmed,
                    raw_scenario=raw, current_operation=current_operation, initial_tanks=initial_tanks)
        except (KeyError, TypeError, ValueError) as exc:
            return {**entry, "outcome": "not_evaluable", "reason": str(exc)[:200]}
        altered_plan = (decision.get("selected_plan") or {}).get("plan_id")
        same = decision.get("status") == status and altered_plan == plan_id
        return {**entry, "outcome": "same" if same else "changed",
                "status": decision.get("status"), "plan_id": altered_plan,
                "reason": str(decision.get("reason"))[:200]}

    def _maker(self, scenario, raw):
        maker = self.decision_factory(scenario)
        maker.scenario_parser = self.scenario_parser
        # The standalone compatibility API also needs mandatory stresses;
        # default_tank_estimate_factory supplies a plain decision factory.
        if maker.robustness_evaluator is None:
            from neftecode.application.services.robustness import RobustnessCheck
            maker.robustness_evaluator = RobustnessCheck(scenario, raw, scenario_parser=self.scenario_parser)
        return maker
