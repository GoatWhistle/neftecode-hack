import math

LEVELS = ("none", "low", "medium", "high")

NO_RISK_TEXT = "Ограничения выдерживаются с запасом; риска, требующего действия оператора, расчёт не показал"


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _worse(current: str, candidate: str) -> str:
    return candidate if LEVELS.index(candidate) > LEVELS.index(current) else current


def _gate_items(decision: dict) -> list[dict]:
    checks = (decision.get("gate") or {}).get("checks") or []
    items = []
    for check in checks:
        if check.get("status") == "fail":
            items.append({"kind": "constraint_violated", "level": "high",
                          "text": f"Нарушено ограничение {check.get('constraint_id')}: {check.get('reason')}",
                          "constraint_id": check.get("constraint_id"), "time_hours": check.get("time_hours")})
        elif check.get("status") == "unknown":
            items.append({"kind": "constraint_unknown", "level": "medium",
                          "text": f"Ограничение {check.get('constraint_id')} не проверено: {check.get('reason')}",
                          "constraint_id": check.get("constraint_id"), "time_hours": check.get("time_hours")})
    return items


def _lookahead_items(decision: dict) -> list[dict]:
    look = decision.get("lookahead") or {}
    if not look.get("available"):
        return []
    selected = look.get("selected") or {}
    window = look.get("min_reaction_hours")
    remaining = selected.get("hours_to_violation")
    stock_ends = selected.get("stock_ends_at_hours")
    items = []
    if _finite(remaining) and _finite(window) and remaining < window:
        items.append({"kind": "violation_beyond_horizon", "level": "high",
                      "text": (f"За горизонтом {selected.get('constraint')} выходит за предел через "
                               f"{remaining:g} ч — раньше запаса реакции {window:g} ч"),
                      "time_hours": remaining})
    elif _finite(stock_ends) and _finite(window) and stock_ends < window:
        items.append({"kind": "stock_ends_beyond_horizon", "level": "medium",
                      "text": (f"Нарушения качества за горизонтом не найдено, но запас компонента кончится "
                               f"через {stock_ends:g} ч — раньше запаса реакции {window:g} ч; "
                               f"дальше этого момента план не проверен"),
                      "time_hours": stock_ends})
    if look.get("switched"):
        items.append({"kind": "plan_switched", "level": "low",
                      "text": (f"Исходный план {look.get('initial_plan')} упирался в предел за горизонтом, "
                               f"поэтому выбран другой допустимый план")})
    return items


def _robustness_items(decision: dict) -> list[dict]:
    robustness = decision.get("robustness") or {}
    if not robustness.get("fragile"):
        return []
    violated = [r.get("perturbation") for r in (robustness.get("results") or [])
                if r.get("outcome") == "violated"]
    return [{"kind": "fragile_plan", "level": "medium",
             "text": ("План теряет допустимость при заявленном отклонении: "
                      + "; ".join(str(v) for v in violated[:3])
                      + ". Как надёжный он не выдаётся"),
             "perturbations": violated[:5]}]


def _tank_estimate_items(decision: dict) -> list[dict]:
    estimate = decision.get("tank_estimate") or {}
    if not estimate.get("available"):
        return []
    if not estimate.get("sensitive"):
        return []
    changed = [r.get("perturbation") for r in (estimate.get("results") or [])
               if r.get("outcome") == "changed"]
    return [{"kind": "tank_estimate_sensitive", "level": "medium",
             "text": ("Решение зависит от оценки состава резервуара, которую мы не измеряли: "
                      "рекомендация меняется при отклонении " + "; ".join(str(c) for c in changed[:3])
                      + ". Состояние резервуара стоит уточнить прямой пробой до исполнения"),
             "perturbations": changed[:5]}]


def _warning_items(warnings: list) -> list[dict]:
    return [{"kind": w.get("kind", "warning"), "level": "medium", "text": w.get("text")}
            for w in (warnings or []) if w.get("text")]


def _trust_items(decision: dict) -> list[dict]:
    for entry in decision.get("trace") or []:
        if not isinstance(entry, dict) or entry.get("agent") != "data":
            continue
        report = entry.get("report") or {}
        items = []
        degraded = [name for name, source in (report.get("sources") or {}).items()
                    if not source.get("usable")]
        if degraded:
            items.append({"kind": "source_degraded", "level": "medium",
                          "text": ("Источник вне доверия: " + ", ".join(degraded)
                                   + f"; решение опирается на {report.get('primary')}"),
                          "sources": degraded})
        suspect = report.get("suspect_values") or []
        if suspect:
            items.append({"kind": "suspect_values", "level": "low",
                          "text": f"Подозрительных значений в срезе: {len(suspect)}"})
        return items
    return []


def _refusal_items(decision: dict) -> list[dict]:
    refusal = decision.get("refusal") or {}
    if not refusal:
        return []
    missing = refusal.get("missing") or []
    if refusal.get("kind") == "data":
        return [{"kind": "refused_on_data", "level": "high",
                 "text": ("Решение не выдано: данные не пригодны для расчёта"
                          + (". Не хватает: " + ", ".join(str(m) for m in missing[:3]) if missing else "")),
                 "missing": list(missing)}]
    if refusal.get("kind") == "agent_rejected":
        return [{"kind": "refused_by_agents", "level": "high",
                 "text": ("Решение не выдано: допустимый план был, но агенты качества/надёжности его отклонили. "
                          "Режим остаётся прежним, и риск, из-за которого план отклонили, никуда не делся")}]
    return [{"kind": "refused_no_plan", "level": "high",
             "text": ("Решение не выдано: допустимого плана нет. Режим остаётся прежним, "
                      "и риск, из-за которого план не найден, никуда не делся")}]


def risk_block(decision: dict, warnings: list | None = None) -> dict:
    items = (_refusal_items(decision) + _gate_items(decision) + _lookahead_items(decision)
             + _robustness_items(decision) + _tank_estimate_items(decision)
             + _warning_items(warnings) + _trust_items(decision))
    level = "none"
    for item in items:
        level = _worse(level, item["level"])
    ordered = sorted(items, key=lambda i: -LEVELS.index(i["level"]))
    return {"level": level, "items": ordered,
            "headline": ordered[0]["text"] if ordered else NO_RISK_TEXT,
            "scope": ("Риск собран из проверенных ограничений, проекции за горизонт, проверок устойчивости "
                      "и чувствительности к оценке резервуара и состояния источников. Это перечень посчитанного, а не вероятность отказа.")}
