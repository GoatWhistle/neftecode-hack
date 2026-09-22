"""Компактный контракт последствий выбранного плана и hold во времени (P1).

Строится из тех же проверок, что уже посчитал Gate для выбранного плана; для hold —
из того же evaluator на тех же входах (пул поиска, либо один ограниченный пересчёт).
LLM не вызывается: расчёт идёт один раз внутри decide(), не на каждое переключение вкладки.
"""

from neftecode.domain.production.quantities import UNITS
from neftecode.domain.shared.primitives import PRODUCT_LIMITS

from ..plan_operation import PlannerError

CONSEQUENCES_VERSION = 1


class ConsequencesMixin:

    def _consequences(self, chosen, final, feasible, plans, confirmed, initial_tanks, current_operation) -> dict:
        selected_id = chosen.plan_id
        hold_evaluation, hold_source, hold_reason = None, None, None
        if selected_id == "hold":
            hold_evaluation, hold_source = final, "selected_is_hold"
        else:
            hold_evaluation = next((e for e in feasible if e.candidate.candidate_id == "hold"), None)
            if hold_evaluation is not None:
                hold_source = "search_pool"
            else:
                hold_plan = next((p for p in plans if p.plan_id == "hold"), None)
                if hold_plan is None:
                    hold_reason = "план hold не построен для этого сценария"
                else:
                    try:
                        hold_evaluation = self._evaluate_plan(hold_plan, confirmed, initial_tanks, current_operation)
                        hold_source = "recomputed_same_evaluator"
                    except (PlannerError, ValueError) as exc:
                        hold_reason = f"расчёт hold тем же evaluator завершился ошибкой: {str(exc)[:160]}"

        def points_for(evaluation, limit_id: str) -> list:
            constraint = f"quality.{limit_id}"
            return [{"t": c.time_hours, "value": c.observed, "status": c.status}
                    for c in evaluation.gate.checks if c.constraint_id == constraint]

        def applicability_for(evaluation) -> list:
            return [{"t": t, "value": value} for t, value in evaluation.applicability]

        series = []
        for limit_id, (prop, direction) in PRODUCT_LIMITS.items():
            quantity = self.scenario.product.limits.get(limit_id)
            candidates = {"selected": {"candidate_id": selected_id, "points": points_for(final, limit_id)}}
            if hold_evaluation is not None:
                candidates["hold"] = {"candidate_id": "hold", "points": points_for(hold_evaluation, limit_id)}
            series.append({
                "limit_id": limit_id, "quality": prop, "unit": UNITS.get(prop), "direction": direction,
                "limit": {"value": quantity.value if quantity is not None else None,
                          "source": quantity.source if quantity is not None else None},
                "candidates": candidates,
            })

        applicability = {"selected": applicability_for(final)}
        if hold_evaluation is not None:
            applicability["hold"] = applicability_for(hold_evaluation)

        return {
            "version": CONSEQUENCES_VERSION,
            "selected_id": selected_id,
            "horizon_hours": self.scenario.horizon.hours,
            "step_hours": self.scenario.horizon.step_minutes / 60,
            "series": series,
            "applicability": applicability,
            "hold": {"available": hold_evaluation is not None,
                     "candidate_id": "hold" if hold_evaluation is not None else None,
                     "source": hold_source, "reason": hold_reason},
            "note": ("Модельные последствия по расчёту Gate на горизонте решения, не доказанный "
                     "эффект на заводе. Длинный прогноз за горизонтом сюда не входит."),
        }
