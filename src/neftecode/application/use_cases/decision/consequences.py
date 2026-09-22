"""Компактный контракт последствий выбранного плана и hold во времени (P1).

Строится из тех же проверок, что уже посчитал Gate для выбранного плана; для hold —
из того же evaluator на тех же входах, но только если он уже посчитан в исследованном
пуле (`feasible`) этого решения. Лишний вызов evaluator здесь не делаем: decide() уже
устроен так, что число вычислений плана — наблюдаемая величина (используется другими
проверками), рассчитывать hold ещё раз в этом месте значило бы завести второй evaluator
поверх первого. Если hold не в пуле — явная недоступность сравнения с причиной, как и
разрешает задание. LLM не вызывается: расчёт идёт один раз внутри decide(), не на каждое
переключение вкладки.
"""

from neftecode.domain.production.quantities import UNITS
from neftecode.domain.shared.primitives import PRODUCT_LIMITS

CONSEQUENCES_VERSION = 1


class ConsequencesMixin:

    def _consequences(self, chosen, final, feasible, by_id=None, confirmed=(), current_operation=None) -> dict:
        selected_id = chosen.plan_id
        hold_evaluation, hold_source, hold_reason, hold_plan = None, None, None, None
        if selected_id == "hold":
            hold_evaluation, hold_source, hold_plan = final, "selected_is_hold", chosen
        else:
            hold_evaluation = next((e for e in feasible if e.candidate.candidate_id == "hold"), None)
            if hold_evaluation is not None:
                hold_source = "search_pool"
                hold_plan = (by_id or {}).get("hold")
            else:
                hold_reason = ("Сохранение текущего режима не входит в допустимый проверенный пул этого "
                               "решения: его траектория здесь не рассчитана и не показывается")

        def events_for(plan) -> list | None:
            if plan is None:
                return None
            return self.planner.action_events(plan, confirmed, current_operation)

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
        events = {"selected": events_for(chosen)}
        if hold_evaluation is not None:
            applicability["hold"] = applicability_for(hold_evaluation)
            events["hold"] = events_for(hold_plan)

        return {
            "version": CONSEQUENCES_VERSION,
            "selected_id": selected_id,
            "horizon_hours": self.scenario.horizon.hours,
            "step_hours": self.scenario.horizon.step_minutes / 60,
            "series": series,
            "applicability": applicability,
            "events": events,
            "hold": {"available": hold_evaluation is not None,
                     "candidate_id": "hold" if hold_evaluation is not None else None,
                     "source": hold_source, "reason": hold_reason},
            "note": ("Модельные последствия по расчёту Gate на горизонте решения, не доказанный "
                     "эффект на заводе. Длинный прогноз за горизонтом сюда не входит."),
            "events_note": ("Моменты действий и объявленного запаздывания отклика взяты из плана и "
                            "сценария; отклик относится к потоку после своей стадии, качество товарной "
                            "смеси меняется по мере поступления в резервуар."),
        }
