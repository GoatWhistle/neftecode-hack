import math

CRITERIA = (
    ("production_t", "выпуск", "т", "max"),
    ("cost_per_tonne", "стоимость", "у.е./т", "min"),
    ("severity_index", "тяжесть режима", "", "min"),
    ("changes", "число изменений", "", "min"),
)

COMPARISON_RULE = ("Планы сравниваются по порядку: больший выпуск, затем меньшая стоимость тонны, "
                   "затем меньшая тяжесть режима, затем меньшее число изменений, затем меньший идентификатор. "
                   "Порядок объявлен до расчёта и не зависит от результата.")

TIE_TEXT = "Совпадает с выбранным планом по всем критериям сравнения; выбран план с меньшим идентификатором"

UNKNOWN_TEXT = "Сравнение неполно: у варианта нет части показателей, поэтому он поставлен после планов с известными числами"


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _format(value: float, unit: str) -> str:
    text = f"{value:.4g}"
    return f"{text} {unit}".strip()


def why_not(alternative: dict, selected: dict) -> str:
    if alternative.get("feasible") is False:
        reasons = alternative.get("rejection_reasons") or []
        if reasons:
            return "Не проходит жёсткие ограничения: " + "; ".join(str(r) for r in reasons[:2])
        return "Не проходит жёсткие ограничения"
    unknown = False
    for key, name, unit, direction in CRITERIA:
        mine, theirs = alternative.get(key), selected.get(key)
        if not _finite(mine) or not _finite(theirs):
            unknown = unknown or not _finite(mine)
            continue
        if mine == theirs:
            continue
        gap = abs(mine - theirs)
        worse = mine < theirs if direction == "max" else mine > theirs
        if not worse:
            continue
        return (f"Проигрывает по критерию «{name}»: {_format(mine, unit)} против "
                f"{_format(theirs, unit)} у выбранного плана, разница {_format(gap, unit)}")
    if unknown:
        return UNKNOWN_TEXT
    return TIE_TEXT


def selected_figures(decision: dict) -> dict:
    plan = decision.get("selected_plan") or {}
    return {"production_t": decision.get("production_t"),
            "cost_per_tonne": decision.get("cost_per_tonne"),
            "severity_index": decision.get("severity_index"),
            "changes": plan.get("changes")}


def alternative_view(alternative: dict, selected: dict) -> dict:
    return {"candidate_id": alternative.get("candidate_id"),
            "production_t": alternative.get("production_t"),
            "cost_per_tonne": alternative.get("cost_per_tonne"),
            "severity_index": alternative.get("severity_index"),
            "changes": alternative.get("changes"),
            "why_not": why_not(alternative, selected)}
