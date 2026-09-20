import hashlib
import json
import math

from neftecode.domain.production.offspec import offspec_block
from neftecode.domain.shared.primitives import SCENARIO_SCOPE
from ..plan_operation import PlannerError
from .constants import LOOKAHEAD_CANDIDATES


class LookaheadMixin:

    def _look_ahead(self, selected, plan_obj, feasible, by_id, confirmed, initial_tanks, current_operation):
        policy = self.scenario.policy or {}
        hours, window = policy.get("lookahead_hours"), policy.get("min_reaction_hours")
        numbers = all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
                      for v in (hours, window))
        if not numbers or hours <= 0 or window <= 0:
            return None, selected, plan_obj
        plan_id = selected["selected"]["candidate_id"]
        plan = plan_obj or by_id[plan_id]
        first = self.planner.lookahead(plan, hours, confirmed, initial_tanks, current_operation)
        result = {"available": True, "lookahead_hours": hours, "min_reaction_hours": window,
                  "initial_plan": plan_id, "initial": first, "selected": first, "switched": False,
                  "examined": 0, "warning": None}
        if first["hours_to_violation"] is None or first["hours_to_violation"] >= window:
            result["offspec"] = self._offspec(selected, feasible, confirmed, initial_tanks, current_operation)
            return result, selected, plan
        best_reach, best_eval, best_info = first["hours_to_violation"], None, first
        for evaluation in sorted(feasible, key=lambda e: e.key()):
            candidate_id = evaluation.candidate.candidate_id
            if candidate_id == plan_id or candidate_id not in by_id:
                continue
            if result["examined"] >= LOOKAHEAD_CANDIDATES:
                break
            result["examined"] += 1
            try:
                info = self.planner.lookahead(by_id[candidate_id], hours, confirmed, initial_tanks, current_operation)
            except (PlannerError, ValueError):
                continue
            if info["hours_to_violation"] is not None:
                reach = info["hours_to_violation"]
            elif info["stock_ends_at_hours"] is not None:
                reach = 0.0
            else:
                reach = math.inf
            if reach > best_reach:
                best_reach, best_eval, best_info = reach, evaluation, info
            if reach >= window:
                break
        what = (f"{first['constraint'].split('.', 1)[1]} = {first['observed']:.2f} при пределе {first['limit']:g}"
                if first["observed"] is not None else first["constraint"])
        if best_eval is not None:
            selected = {**selected, "selected": best_eval.to_dict(),
                        "reason": (f"Упреждение за горизонтом: при плане {plan_id} {what} через "
                                   f"{first['hours_to_violation']:g} ч, раньше запаса реакции {window:g} ч; "
                                   f"выбран допустимый план, отодвигающий нарушение")}
            plan = by_id[best_eval.candidate.candidate_id]
            result.update(selected=best_info, switched=True)
        remaining = result["selected"]["hours_to_violation"]
        stock_ends = result["selected"]["stock_ends_at_hours"]
        if remaining is not None and remaining < window:
            result["warning"] = (f"Предупреждение: при сохранении выбранного плана за горизонтом "
                                 f"{result['selected']['constraint'].split('.', 1)[1]} выйдет за предел через "
                                 f"{remaining:g} ч; допустимого плана с запасом реакции {window:g} ч не найдено")
        elif remaining is None and stock_ends is not None and stock_ends < window:
            result["warning"] = (f"Предупреждение: выбранный план отодвигает нарушение качества, но запас компонента "
                                 f"закончится через {stock_ends:g} ч, раньше запаса реакции {window:g} ч")
        result["offspec"] = self._offspec(selected, feasible, confirmed, initial_tanks, current_operation)
        return result, selected, plan

    def _offspec(self, selected, feasible, confirmed, initial_tanks, current_operation) -> dict:
        chosen = selected["selected"]
        hold = next((e for e in feasible if e.candidate.candidate_id == "hold"), None)
        hold_cost = hold.cost_per_tonne if hold is not None else None
        if hold_cost is None:
            try:
                plans, _ = self._build_plans(1, current_operation)
                hold_plan = next((p for p in plans if p.plan_id == "hold"), None)
                if hold_plan is not None:
                    hold_cost = self._evaluate_plan(
                        hold_plan, confirmed, initial_tanks, current_operation).cost_per_tonne
            except (PlannerError, ValueError):
                hold_cost = None
        block = offspec_block(self.scenario, hold_cost, chosen.get("cost_per_tonne"),
                              chosen.get("production_t"), initial_tanks)
        block["hold_feasible"] = hold is not None
        return block

    def _finish(self, status, reason, trace, plan, evaluation, refusal, ranking=None,
                robustness=None, current_operation=None, lookahead=None,
                tank_estimate=None) -> dict:
        required_inputs = list((self.scenario.policy or {}).get("deployment_inputs") or ())
        ready = not any(item.get("status") == "open" for item in required_inputs)
        result = {
            "status": status, "reason": reason, "scope": SCENARIO_SCOPE,
            "current_operation": current_operation,
            "commercial_release_allowed": False,
            "deployment_readiness": {
                "ready": ready,
                "reason": ("Все обязательные заводские параметры переданы."
                           if ready else "Для промышленного применения завод должен передать фактические "
                           "параметры парка и допустимую мощность глубокой очистки."),
                "required_inputs": required_inputs,
            },
            "scenario_id": self.scenario.scenario_id,
            "selected_plan": plan.to_dict() if plan is not None else None,
            "immediate_action": plan.steps[0].to_advice_dict() if plan is not None else None,
            "gate": evaluation.gate.to_dict() if evaluation is not None else None,
            "production_t": evaluation.production_t if evaluation is not None else None,
            "cost_per_tonne": evaluation.cost_per_tonne if evaluation is not None else None,
            "severity_index": evaluation.severity_index if evaluation is not None else None,
            "alternatives": (ranking or {}).get("alternatives", []),
            "rejected": (ranking or {}).get("rejected", []),
            "selection_policy": {
                "ranking": (ranking or {}).get("ranking"),
                "severity_cost_tolerance_fraction": (ranking or {}).get(
                    "severity_cost_tolerance_fraction", 0.0),
                "max_severity_index": (ranking or {}).get("max_severity_index"),
                "reliability_tradeoff": (ranking or {}).get("reliability_tradeoff"),
            } if ranking is not None else None,
            "refusal": refusal,
            "robustness": robustness,
            "tank_estimate": tank_estimate,
            "lookahead": lookahead,
            "trace": trace,
            "note": ("Результат сценарный. Выданный план не считается исполненным и не разрешает "
                     "выпуск товарного топлива."),
        }
        content = json.dumps(result, sort_keys=True, ensure_ascii=False, default=str)
        result["decision_id"] = hashlib.sha256(content.encode()).hexdigest()[:16]
        return result
