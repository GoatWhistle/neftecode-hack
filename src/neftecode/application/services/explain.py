"""Turning a decision into something an operator can check, line by line.

Every statement here is built from a number the calculation actually produced, and carries the
reference that number came from: an observation, a scenario parameter, a model version or a
named gate check. A non-empty citation is not enough — the value in the statement and the value
in the evidence are the same object, so a claim cannot drift away from the computation.

What is deliberately impossible to say:

* an unverified "process cause". Nothing here explains *why* the plant behaves as it does; it
  explains what was computed, from which inputs, and which limits were checked.
* a refusal without a next step. Each refusal names its kind — bad data, an unusable model, or
  no feasible plan — and what would have to change, including how long that would take.
"""
from dataclasses import dataclass
import math

from neftecode.domain.shared.primitives import FAIL, PASS, UNKNOWN
from neftecode.domain.production.scenario import QUALITIES, Scenario

#: Kinds of refusal. They are answered differently, so they are never merged.
BAD_DATA = "bad_data"
MODEL_NOT_APPLICABLE = "model_not_applicable"
NO_FEASIBLE_PLAN = "no_feasible_plan"
REFUSAL_KINDS = (BAD_DATA, MODEL_NOT_APPLICABLE, NO_FEASIBLE_PLAN)

#: How long a fresh laboratory result takes to arrive, per the expert (message 517).
LAB_DELAY_HOURS = 4.0


class ExplanationError(ValueError):
    """Raised when a statement is offered without a checkable basis."""


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


@dataclass(frozen=True)
class Evidence:
    """A pointer the reader can re-open, carrying the same value as the statement."""

    kind: str
    ref: str
    value: float | None = None
    detail: str | None = None

    KINDS = ("observation", "scenario", "model", "gate_check", "policy")

    def __post_init__(self):
        if self.kind not in self.KINDS:
            raise ExplanationError(f"Неизвестный вид ссылки: {self.kind}")
        if not self.ref or not self.ref.strip():
            raise ExplanationError("Ссылка обязана называть источник")
        if self.value is None and not self.detail:
            raise ExplanationError(f"Ссылка на {self.ref} пуста: нужно значение или пояснение")

    def to_dict(self) -> dict:
        return {"kind": self.kind, "ref": self.ref, "value": self.value, "detail": self.detail}


@dataclass(frozen=True)
class Statement:
    """One line of the explanation, bound to the number it talks about."""

    topic: str
    text: str
    value: float | None
    evidence: tuple[Evidence, ...]

    def __post_init__(self):
        if not self.evidence:
            raise ExplanationError(f"{self.topic}: утверждение без ссылки запрещено")
        if self.value is not None:
            matching = [e for e in self.evidence
                        if e.value is not None and abs(e.value - self.value) < 1e-6]
            if not matching:
                raise ExplanationError(
                    f"{self.topic}: число {self.value} в утверждении не совпадает ни с одной ссылкой")

    def to_dict(self) -> dict:
        return {"topic": self.topic, "text": self.text, "value": self.value,
                "evidence": [e.to_dict() for e in self.evidence]}


def explain_decision(decision: dict, scenario: Scenario) -> dict:
    """Build the operator-facing explanation of a decision that produced a plan."""
    statements: list[Statement] = []
    gate = decision.get("gate") or {}
    checks = gate.get("checks", [])

    for quality in QUALITIES:
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
        # Report the tightest point of the plan, not the first: that is the one that could fail.
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

    lag = scenario.stages["hydrotreating"].response_lag_hours.value
    statements.append(Statement(
        "delay", f"Эффект коррекции гидроочистки ожидается через {lag:g} ч", lag,
        (Evidence("scenario", "stages.hydrotreating.response_lag_hours", lag,
                  "объявленное запаздывание отклика"),)))

    return {
        "status": decision.get("status"),
        "reason": decision.get("reason"),
        "statements": [s.to_dict() for s in statements],
        "current_operation": decision.get("current_operation") or {
            "controls": {name: spec["current"].value
                         for stage in scenario.stages.values()
                         for name, spec in stage.controls.items()},
            "recipe": dict(scenario.current_operation.recipe),
            "throughput_tph": scenario.current_operation.throughput.value,
            "additive_dose": 0.0,
        },
        "component_names": {tank.tank_id: tank.name for tank in scenario.tanks},
        "checks_passed": sum(1 for c in checks if c["status"] == PASS),
        "checks_total": len(checks),
        "alternatives": [
            {"candidate_id": a["candidate_id"], "production_t": a.get("production_t"),
             "cost_per_tonne": a.get("cost_per_tonne"),
             "why_not": "Проигрывает по правилу сравнения: выпуск, затем стоимость, затем тяжесть режима"}
            for a in decision.get("alternatives", [])[:5]],
        "limits": [
            "Объяснение описывает расчёт и проверенные ограничения, а не причину поведения установки.",
            "Изменение режима исполняет регулятор по новой уставке; динамика самого контура не моделируется.",
            "Все параметры смешения, цен и откликов заданы сценарием и не получены из данных завода.",
            "Результат не разрешает выпуск товарного топлива: проверены не все требуемые свойства.",
        ],
    }


def explain_refusal(decision: dict, scenario: Scenario) -> dict:
    """Build a refusal that says what is missing and what would change the answer.

    The three kinds are answered differently: bad data needs a measurement, an inapplicable
    model needs a regime inside its declared region, and an infeasible plan needs a resource
    or a relaxed *scenario* condition — never a relaxed hard limit.
    """
    refusal = decision.get("refusal") or {}
    kind = refusal.get("kind")
    if kind == "data":
        kind = BAD_DATA
    elif kind == "final_recheck_failed":
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
    else:
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
        "limits": [
            "Отказ не снимается ослаблением жёстких ограничений: предел серы 10 мг/кг и другие "
            "обязательные условия остаются в силе.",
            "Дополнительный анализ не мгновенен и может прийти позже горизонта действия.",
            "Отказ означает отсутствие надёжной рекомендации, а не отсутствие риска.",
        ],
    }


def explain(decision: dict, scenario: Scenario) -> dict:
    """Dispatch to the right explanation for the decision's status."""
    if decision.get("status") == "refuse":
        return explain_refusal(decision, scenario)
    return explain_decision(decision, scenario)
