
from neftecode.application.services.comparison import COMPARISON_RULE, alternative_view, selected_figures
from neftecode.application.services.risk_block import risk_block
from neftecode.domain.shared.primitives import PASS, UNKNOWN
from neftecode.domain.production.scenario import Scenario
from neftecode.domain.shared.primitives import PRODUCT_LIMITS

from .explain_types import (BAD_DATA, Evidence, ExplanationError, LAB_DELAY_HOURS, MODEL_NOT_APPLICABLE,
                            NO_FEASIBLE_PLAN, REFUSAL_KINDS, Statement, _finite, current_operation_view,
                            operating_margin_warnings)
from .refusal import explain_refusal

__all__ = ["BAD_DATA", "Evidence", "ExplanationError", "LAB_DELAY_HOURS", "MODEL_NOT_APPLICABLE",
           "NO_FEASIBLE_PLAN", "REFUSAL_KINDS", "Statement", "current_operation_view", "explain",
           "explain_decision", "explain_refusal", "operating_margin_warnings"]


def explain_decision(decision: dict, scenario: Scenario, state: dict | None = None) -> dict:
    statements: list[Statement] = []
    gate = decision.get("gate") or {}
    checks = gate.get("checks", [])

    for quality in PRODUCT_LIMITS:
        own = [c for c in checks if c["constraint_id"] == f"quality.{quality}"]
        unknown = [c for c in own if c["status"] == UNKNOWN]
        if unknown:
            statements.append(Statement(
                quality, f"{quality}: значение неизвестно — {unknown[0]['reason']}", None,
                (Evidence("gate_check", unknown[0]["constraint_id"], None, unknown[0]["reason"]),)))
            continue
        passing = [c for c in own if c["status"] == PASS and c["observed"] is not None
                   and c["limit"] is not None]
        if not passing:
            continue
        tightest = min(passing, key=lambda c: abs(c["limit"] - c["observed"]))
        statements.append(Statement(
            quality,
            f"{quality}: самая близкая к пределу точка плана даёт {tightest['observed']:.3f} "
            f"при пределе {tightest['limit']:g} на {tightest['time_hours']:g} ч",
            tightest["observed"],
            (Evidence("gate_check", tightest["constraint_id"], tightest["observed"],
                      f"предел {tightest['limit']}, момент {tightest['time_hours']} ч"),
             Evidence("scenario", f"product.{quality}", tightest["limit"],
                      "предел задан сценарием или ТЗ"))))

    action = decision.get("immediate_action")
    if action:
        standing = (decision.get("current_operation") or {}).get("controls") or {}
        actuations = {name: (stage_id, spec.get("actuation"))
                      for stage_id, stage in scenario.stages.items()
                      for name, spec in stage.controls.items()}
        for name, value in sorted(action.get("controls", {}).items()):
            stage_id, actuation = actuations.get(name, (None, None))
            evidence = [Evidence("scenario", f"controls.{name}", value, "уставка из плана")]
            text = f"{name}: предлагаемое значение {value:g}"
            if actuation is not None:
                lag = scenario.stages[stage_id].response_lag_hours.value
                current = standing.get(name, scenario.stages[stage_id].controls[name]["current"].value)
                if abs(value - current) < 1e-9:
                    text = f"{name}: сохранить уставку регулятора {value:g} ({actuation.loop})"
                else:
                    text = (f"{name}: {actuation.instruction} с {current:g} до {value:g} ({actuation.loop}); "
                            f"регулятор отрабатывает задание, качество отвечает через {lag:g} ч")
                tag = f"тег {actuation.measured_tag}; " if actuation.measured_tag else "тег CSV не подписан; "
                evidence.append(Evidence("scenario", f"stages.{stage_id}.controls.{name}.actuation",
                                         None, tag + (actuation.note or actuation.source)))
            statements.append(Statement(f"control.{name}", text, value, tuple(evidence)))
        throughput = action.get("throughput_tph")
        if _finite(throughput):
            statements.append(Statement(
                "throughput", f"Выпуск {throughput:g} т/ч", throughput,
                (Evidence("scenario", "plan.throughput_tph", throughput, "выпуск из плана"),)))

    production = decision.get("production_t")
    if _finite(production):
        statements.append(Statement(
            "production", f"Ожидаемый выпуск за горизонт {production:.1f} т", production,
            (Evidence("model", "economics.summarise", production, "сумма по шагам плана"),)))
    cost = decision.get("cost_per_tonne")
    if _finite(cost):
        statements.append(Statement(
            "cost", f"Условная стоимость {cost:.4f} на тонну", cost,
            (Evidence("model", "economics.cost_per_tonne", cost,
                      "условные единицы сценария, не тарифы завода"),)))
    severity = decision.get("severity_index")
    if _finite(severity):
        statements.append(Statement(
            "severity", f"Показатель тяжести режима {severity:.3f}", severity,
            (Evidence("model", "economics.severity", severity,
                      "индекс режима, не возраст катализатора и не вероятность отказа"),)))

    look = decision.get("lookahead") or {}
    if look.get("available"):
        projected = look.get("selected") or {}
        remaining = projected.get("hours_to_violation")
        evidence_note = projected.get("assumption") or "расчёт за горизонтом"
        if remaining is not None:
            name = str(projected.get("constraint", "quality")).split(".", 1)[-1]
            statements.append(Statement(
                "lookahead",
                f"За горизонтом: при сохранении плана {name} выйдет за предел через {remaining:g} ч "
                f"(запас реакции {look.get('min_reaction_hours'):g} ч)",
                remaining, (Evidence("model", "plan_operation.lookahead", remaining, evidence_note),)))
        else:
            stock = projected.get("stock_ends_at_hours")
            tail = (f"; расчёт остановлен на {stock:g} ч, когда заканчивается запас компонента"
                    if stock is not None else "")
            statements.append(Statement(
                "lookahead",
                f"За горизонтом {look.get('lookahead_hours'):g} ч нарушений качества при сохранении плана не видно{tail}",
                None, (Evidence("model", "plan_operation.lookahead", None, evidence_note),)))

    lag_quantity = scenario.stages["hydrotreating"].response_lag_hours
    lag = lag_quantity.value
    share = (scenario.stages["hydrotreating"].model or {}).get("horizon_response_share")
    text = f"Эффект коррекции гидроочистки ожидается через {lag:g} ч"
    if _finite(share) and share < 1:
        text += f"; в пределах горизонта засчитывается не больше {share:.0%} хода температуры"
    statements.append(Statement(
        "delay", text, lag,
        (Evidence("model" if lag_quantity.source == "derived" else "scenario",
                  "stages.hydrotreating.response_lag_hours", lag,
                  lag_quantity.note or "объявленное запаздывание отклика"),)))

    warnings = operating_margin_warnings(decision, scenario)
    return {
        "status": decision.get("status"),
        "reason": decision.get("reason"),
        "statements": [s.to_dict() for s in statements],
        "current_operation": current_operation_view(decision, scenario, state),
        "component_names": {tank.tank_id: tank.name for tank in scenario.tanks},
        "warnings": warnings,
        "risk": risk_block(decision, warnings),
        "checks_passed": sum(1 for c in checks if c["status"] == PASS),
        "checks_total": len(checks),
        "alternatives": [alternative_view(a, selected_figures(decision))
                         for a in decision.get("alternatives", [])[:5]],
        "comparison_rule": COMPARISON_RULE,
        "limits": [
            "Объяснение описывает расчёт и проверенные ограничения, а не причину поведения установки.",
            "Изменение режима исполняет регулятор по новой уставке; динамика самого контура не моделируется.",
            "Фактические объём и вместимость резервуарного парка, а также допустимая мощность "
            "наработки глубокоочищенного компонента должны быть переданы заводом; 4000 т и 30 т/ч — сценарий.",
            "Результат не разрешает выпуск товарного топлива: проверены не все требуемые свойства.",
        ],
    }


def explain(decision: dict, scenario: Scenario, state: dict | None = None) -> dict:
    if decision.get("status") == "refuse":
        return explain_refusal(decision, scenario, state)
    return explain_decision(decision, scenario, state)
