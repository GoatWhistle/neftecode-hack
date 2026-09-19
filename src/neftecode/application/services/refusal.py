from neftecode.application.services.risk_block import risk_block
from neftecode.domain.production.scenario import Scenario

from .explain_types import (BAD_DATA, LAB_DELAY_HOURS, MODEL_NOT_APPLICABLE, NO_FEASIBLE_PLAN, REFUSAL_KINDS,
                            current_operation_view)


def explain_refusal(decision: dict, scenario: Scenario, state: dict | None = None) -> dict:
    refusal = decision.get("refusal") or {}
    kind = refusal.get("kind")
    if kind == "data":
        kind = BAD_DATA
    elif kind in ("final_recheck_failed", "weak_response_failed"):
        kind = NO_FEASIBLE_PLAN
    elif kind not in REFUSAL_KINDS:
        kind = NO_FEASIBLE_PLAN

    next_steps: list[dict] = []
    if kind == BAD_DATA:
        for missing in refusal.get("missing", []):
            step = {"need": missing, "kind": "measurement"}
            if "лабораторный" in missing:
                step["available_in_hours"] = LAB_DELAY_HOURS
                step["caveat"] = (f"Результат лаборатории появляется до {LAB_DELAY_HOURS:g} ч после "
                                  f"отбора и может не успеть в горизонт {scenario.horizon.hours:g} ч")
            next_steps.append(step)
        if not next_steps:
            next_steps.append({"need": "достоверный источник качества", "kind": "measurement"})
    elif kind == MODEL_NOT_APPLICABLE:
        next_steps.append({"need": "вернуть режим в объявленную область применимости модели",
                           "kind": "regime"})
    elif refusal.get("kind") == "agent_rejected":
        codes = ", ".join(refusal.get("reason_codes", [])[:5]) or "без кода"
        next_steps.append({"need": f"проверить замечания агентов качества и надёжности ({codes})",
                           "kind": "agent_review"})
        next_steps.append({"need": "детерминированный вариант без агентов доступен при выключенном агентном режиме",
                           "kind": "agent_review"})
    else:
        if refusal.get("kind") == "weak_response_failed":
            next_steps.append({"need": (f"план {refusal.get('plan_id')} держит предел только при среднем отклике β; "
                                        "при слабом крае диапазона следующего полугодия предел нарушается — ход "
                                        "температуры не гарантирует качество"),
                               "kind": "resource_or_scenario_condition"})
        for example in refusal.get("examples", [])[:5]:
            next_steps.append({"need": example, "kind": "resource_or_scenario_condition"})
        if not next_steps:
            next_steps.append({"need": "дополнительный запас компонента или иные условия сценария",
                               "kind": "resource_or_scenario_condition"})

    return {
        "status": decision.get("status"),
        "kind": kind,
        "reason": decision.get("reason"),
        "next_steps": next_steps,
        "current_operation": current_operation_view(decision, scenario, state),
        "component_names": {tank.tank_id: tank.name for tank in scenario.tanks},
        "risk": risk_block(decision, []),
        "limits": [
            "Отказ не снимается ослаблением жёстких ограничений: предел серы 10 мг/кг и другие "
            "обязательные условия остаются в силе.",
            "Дополнительный анализ не мгновенен и может прийти позже горизонта действия.",
            "Отказ означает отсутствие надёжной рекомендации, а не отсутствие риска.",
        ],
    }
