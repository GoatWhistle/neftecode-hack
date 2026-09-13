"""Burden of proof before a control recommendation is allowed to leave the system.

History here is observational: an operator moves a setpoint *because* quality moved,
so a model fitted on it can learn the effect backwards. Three checks run before any
control action is offered — does history contain a natural experiment on this tag,
does the proposed setpoint lie inside the data we actually have, and does the tag
lead the target or merely follow it. Failing a check produces a refusal with a reason,
never a quiet lower confidence.
"""
import numpy as np
import pandas as pd


def _standardise(frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    values = frame.to_numpy(float)
    centre = np.nanmedian(values, axis=0)
    scale = np.nanstd(values, axis=0)
    scale = np.where(np.isfinite(scale) & (scale > 1e-9), scale, 1.0)
    return (values - centre) / scale, centre, scale


def natural_experiments(signals: pd.DataFrame, tag: str, context_tags, window_hours: float = 6,
                        move_quantile: float = .9, calm_quantile: float = .25) -> dict:
    """Windows where this tag moved while the rest of the context stayed calm."""
    if tag not in signals.columns:
        raise ValueError(f"Тег {tag} отсутствует в телеметрии")
    context = [c for c in context_tags if c in signals.columns and c != tag]
    if not context:
        raise ValueError("Нужен непустой контекст для поиска естественных экспериментов")
    shift = signals[[tag, *context]].diff(periods=_periods(signals.index, window_hours)).abs()
    scale = shift.std().replace(0, np.nan)
    normalised = shift / scale
    moved = normalised[tag]
    calm = normalised[context].mean(axis=1)
    good = moved.notna() & calm.notna()
    if good.sum() < 100:
        return {"tag": tag, "windows": 0, "usable": False,
                "reason": "Недостаточно наблюдений для поиска естественных экспериментов"}
    move_cut = float(moved[good].quantile(move_quantile))
    calm_cut = float(calm[good].quantile(calm_quantile))
    hit = good & (moved >= move_cut) & (calm <= calm_cut)
    stamps = signals.index[hit]
    return {
        "tag": tag, "context_tags": len(context), "window_hours": float(window_hours),
        "windows": int(hit.sum()), "share_of_history": float(hit.sum() / good.sum()),
        "move_threshold": move_cut, "calm_threshold": calm_cut,
        "first": str(stamps.min()) if len(stamps) else None,
        "last": str(stamps.max()) if len(stamps) else None,
        "usable": bool(hit.sum() >= 30),
        "reason": "Есть окна, где тег двигался при спокойном окружении" if hit.sum() >= 30
                  else "Тег почти не двигается отдельно от остального режима; изолировать его эффект по этой истории нельзя",
        "scope": "Это не поставленный эксперимент. Спокойное окружение оценивается по выбранным тегам контекста, "
                 "неучтенное воздействие остается возможным.",
    }


def _periods(index: pd.DatetimeIndex, hours: float) -> int:
    spacing = pd.Series(index).diff().median()
    if pd.isna(spacing) or spacing <= pd.Timedelta(0):
        raise ValueError("Не удалось определить шаг ряда")
    return max(1, int(round(pd.Timedelta(hours=hours) / spacing)))


def support_check(history: pd.DataFrame, context_columns, tag: str, current_context: dict,
                  proposed_value: float, neighbours: int = 200, inner=(.05, .95)) -> dict:
    """Is the proposed setpoint inside the data, given a comparable operating context?"""
    columns = [c for c in context_columns if c in history.columns and c != tag]
    if not columns or tag not in history.columns:
        raise ValueError("Для проверки опоры нужны контекстные теги и сам тег в истории")
    if not np.isfinite(proposed_value):
        raise ValueError("Предлагаемая уставка должна быть конечным числом")
    table = history[[*columns, tag]].dropna()
    if len(table) < neighbours:
        return {"tag": tag, "supported": False, "neighbours": int(len(table)),
                "reason": "Недостаточно сопоставимой истории для проверки опоры"}
    scaled, centre, scale = _standardise(table[columns])
    point = np.array([current_context.get(c, np.nan) for c in columns], float)
    if not np.isfinite(point).all():
        return {"tag": tag, "supported": False,
                "reason": "Текущий режим описан не полностью; опора не проверяется"}
    distance = np.linalg.norm(scaled - (point - centre) / scale, axis=1)
    nearest = table.iloc[np.argsort(distance)[:neighbours]]
    low, high = (float(nearest[tag].quantile(q)) for q in inner)
    inside = low <= proposed_value <= high
    return {
        "tag": tag, "proposed": float(proposed_value), "neighbours": int(neighbours),
        "observed_low": low, "observed_high": high,
        "context_radius": float(np.sort(distance)[neighbours - 1]),
        "supported": bool(inside),
        "reason": "Уставка попадает в область, наблюдавшуюся в похожем режиме" if inside
                  else f"В похожем режиме этот тег держался в пределах {low:.4g}–{high:.4g}; "
                       f"предложение {proposed_value:.4g} вне наблюдавшейся области",
        "scope": "Опора проверяется по близким режимам в истории, а не по паспортным пределам оборудования.",
    }


def direction_test(signal: pd.Series, target: pd.Series, max_lag_hours: float = 12,
                   step_hours: float = 1) -> dict:
    """Does the tag lead the target, or does the target lead the tag (operator reaction)?"""
    frame = pd.concat([signal.rename("tag"), target.rename("target")], axis=1, join="inner").dropna()
    if len(frame) < 200:
        return {"verdict": "unknown", "reason": "Слишком мало совпадающих наблюдений"}
    step = _periods(frame.index, step_hours)
    top = _periods(frame.index, max_lag_hours)
    grid = range(step, top + 1, step)

    def best(a: pd.Series, b: pd.Series) -> tuple[float, float]:
        pairs = [(lag, a.shift(lag).corr(b)) for lag in grid]
        pairs = [(lag, r) for lag, r in pairs if pd.notna(r)]
        if not pairs:
            return 0.0, 0.0
        lag, r = max(pairs, key=lambda p: abs(p[1]))
        return float(r), lag * step_hours / step
    tag_leads, tag_lag = best(frame.tag, frame.target)
    target_leads, target_lag = best(frame.target, frame.tag)
    margin = abs(tag_leads) - abs(target_leads)
    verdict = "tag_leads" if margin > .02 else "target_leads" if margin < -.02 else "symmetric"
    return {
        "verdict": verdict, "tag_leads_r": tag_leads, "tag_lead_hours": tag_lag,
        "target_leads_r": target_leads, "target_lead_hours": target_lag, "margin": float(margin),
        "confounded": verdict != "tag_leads",
        "reason": {"tag_leads": "Тег опережает показатель качества сильнее, чем наоборот",
                   "target_leads": "Показатель качества опережает тег: похоже на реакцию оператора, а не на воздействие",
                   "symmetric": "Опережение в обе стороны сопоставимо; направление связи из этой истории не следует",
                   }[verdict],
        "scope": "Тест на асимметрию опережения. Он не заменяет причинный вывод и не учитывает общий скрытый фактор.",
    }


class SupportAgent:
    """Refuses control advice the available history cannot back up."""

    def __init__(self, history: pd.DataFrame, target: pd.Series, context_tags):
        self.history = history
        self.target = target
        self.context_tags = list(context_tags)

    def review(self, tag: str, current_context: dict, proposed_value: float) -> dict:
        experiments = natural_experiments(self.history, tag, self.context_tags)
        support = support_check(self.history, self.context_tags, tag, current_context, proposed_value)
        direction = direction_test(self.history[tag], self.target)
        blocking = []
        if not experiments.get("usable"):
            blocking.append(experiments["reason"])
        if not support.get("supported"):
            blocking.append(support["reason"])
        if direction.get("confounded"):
            blocking.append(direction["reason"])
        return {"tag": tag, "allowed": not blocking, "blocking": blocking,
                "natural_experiments": experiments, "support": support, "direction": direction,
                "rule": "Рекомендация по управлению выдается только когда история содержит естественные эксперименты "
                        "с этим тегом, уставка лежит внутри наблюдавшейся области и тег опережает показатель качества."}
