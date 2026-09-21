import math

VERSION = "tradeoff/1"
PRECISION = 1e-6
MAX_DOMINATED_POINTS = 60

CRITERIA = (
    {"key": "production_t", "label": "Выпуск", "unit": "т", "goal": "max"},
    {"key": "cost_per_tonne", "label": "Стоимость на тонну", "unit": "у. е./т", "goal": "min"},
    {"key": "severity_index", "label": "Тяжесть режима", "unit": "индекс", "goal": "min"},
)


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _values(evaluation) -> dict:
    return {"production_t": evaluation.production_t, "cost_per_tonne": evaluation.cost_per_tonne,
            "severity_index": evaluation.severity_index}


def _missing(values: dict) -> list[str]:
    return [c["key"] for c in CRITERIA if not _finite(values.get(c["key"]))]


def _score(values: dict) -> tuple:
    """Все оси приведены к «меньше — лучше»: выпуск берётся с минусом."""
    return (-values["production_t"], values["cost_per_tonne"], values["severity_index"])


def dominates(a: dict, b: dict, precision: float = PRECISION) -> bool:
    """a доминирует b: не хуже по каждой оси и строго лучше хотя бы по одной (с заданной точностью)."""
    sa, sb = _score(a), _score(b)
    no_worse = all(x <= y + precision for x, y in zip(sa, sb))
    strictly_better = any(x < y - precision for x, y in zip(sa, sb))
    return no_worse and strictly_better


def _moves(candidate, hold) -> list[dict]:
    if hold is None:
        return []
    moves = []
    for name, value in sorted(candidate.controls.items()):
        base = hold.controls.get(name)
        if base is not None and abs(value - base) > 1e-9:
            moves.append({"name": name, "from": base, "to": value})
    return moves


def _point(evaluation, hold, front: bool, dominated_by: str | None, selected_id, hold_id) -> dict:
    values = _values(evaluation)
    candidate = evaluation.candidate
    return {"candidate_id": candidate.candidate_id, **values, "changes": candidate.changes,
            "on_front": front, "dominated_by": dominated_by,
            "selected": candidate.candidate_id == selected_id,
            "is_hold": candidate.candidate_id == hold_id,
            "recipe": dict(candidate.recipe), "throughput_tph": candidate.throughput_tph,
            "additive_dose": candidate.additive_dose, "moves": _moves(candidate, hold),
            "gate_passed": True, "stress_checked": False}


def tradeoff_map(pool, selected_id: str | None, hold_id: str = "hold", *, horizon_hours: float | None = None,
                 severity_profile: str | None = None, evaluated: int | None = None, budget: int | None = None,
                 rounds: int | None = None, selection_reason: str | None = None, hold_note: str | None = None,
                 stress_checked_id: str | None = None, robustness: dict | None = None) -> dict:
    """Недоминируемое множество исследованного допустимого пула (после Gate и применённых ограничений).

    Фронт относится к исследованному пулу, а не ко всем физически возможным режимам.
    """
    pool = list(pool or [])
    known, excluded = [], []
    for evaluation in pool:
        missing = _missing(_values(evaluation))
        if missing:
            excluded.append({"candidate_id": evaluation.candidate.candidate_id, "missing": missing})
        else:
            known.append(evaluation)
    hold = next((e.candidate for e in pool if e.candidate.candidate_id == hold_id), None)
    groups: dict[tuple, list] = {}
    for evaluation in sorted(known, key=lambda e: (_score(_values(e)), e.candidate.candidate_id)):
        key = tuple(round(x / PRECISION) for x in _score(_values(evaluation)))
        groups.setdefault(key, []).append(evaluation)

    def representative(members):
        return next((m for m in members if m.candidate.candidate_id in (selected_id, hold_id)), members[0])

    ordered = [(representative(members), members) for members in groups.values()]
    dominators: dict[str, str | None] = {}
    front = []
    for evaluation, members in ordered:
        values = _values(evaluation)
        by = next((other.candidate.candidate_id for other, _ in front
                   if dominates(_values(other), values)), None)
        for member in members:
            dominators[member.candidate.candidate_id] = by
        if by is None:
            front.append((evaluation, members))
    front_ids = {e.candidate.candidate_id for e, _ in front}
    dominated_groups = [(e, m) for e, m in ordered if e.candidate.candidate_id not in front_ids]
    must = [(e, m) for e, m in dominated_groups
            if any(x.candidate.candidate_id in (selected_id, hold_id) for x in m)]
    rest = [g for g in dominated_groups if g not in must]
    room = max(0, MAX_DOMINATED_POINTS - len(must))
    if len(rest) > room:
        step = (len(rest) - 1) / (room - 1) if room > 1 else 0
        rest = [rest[round(i * step)] for i in range(room)] if room else []
    shown = front + must + rest
    points = []
    for evaluation, members in shown:
        point = _point(evaluation, hold, evaluation.candidate.candidate_id in front_ids,
                       dominators.get(evaluation.candidate.candidate_id), selected_id, hold_id)
        point["equivalent_count"] = len(members) - 1
        point["equivalent_ids"] = [m.candidate.candidate_id for m in members
                                   if m is not evaluation][:5]
        point["selected"] = any(m.candidate.candidate_id == selected_id for m in members)
        point["is_hold"] = any(m.candidate.candidate_id == hold_id for m in members)
        points.append(point)
    for point in points:
        if stress_checked_id is not None and point["selected"] and stress_checked_id == selected_id:
            point["stress_checked"] = True
            point["robustness"] = robustness
    selected_known = selected_id in dominators
    selected_on_front = selected_known and dominators[selected_id] is None
    note = None
    if selected_id is not None and selected_known and not selected_on_front:
        note = ("Выбранный план доминируется другим допустимым вариантом; выбор следует действующему правилу "
                "(" + (selection_reason or "правило выбора сохранено") + "), а не расположению на фронте.")
    elif selected_id is not None and not selected_known:
        note = "У выбранного плана нет одного из показателей: его положение на фронте не определено."
    status = "ok" if known else ("empty" if not pool else "unknown_metrics")
    return {
        "version": VERSION, "status": status, "criteria": [dict(c) for c in CRITERIA],
        "precision": PRECISION, "horizon_hours": horizon_hours, "severity_profile": severity_profile,
        "pool": {"admissible": len(pool), "comparable": len(known),
                 "front": sum(len(m) for _, m in front), "front_distinct": len(front),
                 "dominated": len(known) - sum(len(m) for _, m in front),
                 "distinct_points": len(ordered), "excluded_unknown": excluded[:20],
                 "excluded_unknown_count": len(excluded),
                 "points_shown": len(points), "points_truncated": len(points) < len(ordered),
                 "evaluated": evaluated, "search_budget": budget, "rounds": rounds},
        "selected_id": selected_id, "selected_on_front": selected_on_front if selected_known else None,
        "selection_note": note, "selection_reason": selection_reason,
        "hold": {"id": hold_id, "admissible": hold is not None, "note": hold_note},
        "points": points,
        "scope": "Фронт построен по исследованному допустимому пулу текущего расчёта после Gate и "
                 "применённых ограничений; он не охватывает все физически возможные режимы и не меняет "
                 "правило выбора плана.",
        "stress_scope": "«Прошёл Gate» и «прошёл стресс-проверки» — разные вещи: стресс-проверки "
                        "выполнены только для выбранного плана; у остальных точек их не было.",
    }
