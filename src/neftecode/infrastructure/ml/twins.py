"""Case-based evidence: what actually happened the last times the plant looked like this.

Global correlations with the sulfur target are weak, so a fitted surface mostly
reproduces the mean. Nearest historical situations answer a narrower question that
the data can support, and every answer is a list of dates an engineer can open.
"""
import numpy as np
import pandas as pd


def _matrix(frame: pd.DataFrame, columns) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    values = frame[columns].to_numpy(float)
    centre = np.nanmedian(values, axis=0)
    scale = np.nanstd(values, axis=0)
    scale = np.where(np.isfinite(scale) & (scale > 1e-9), scale, 1.0)
    return values, centre, scale


def find_twins(history: pd.DataFrame, current, columns, k: int = 20, before=None,
               exclude_within_hours: float = 48, reference_time=None,
               min_separation_hours: float = 12) -> pd.DataFrame:
    """Closest past situations in standardised tag space. Never looks past `before`.

    Neighbours are forced apart in time: adjacent 10-minute rows of one episode are
    one case, and counting them separately would inflate the evidence.
    """
    columns = [c for c in columns if c in history.columns]
    if not columns:
        raise ValueError("Нет общих тегов для поиска похожих ситуаций")
    table = history[columns].dropna()
    if before is not None:
        table = table.loc[table.index < pd.Timestamp(before)]
    if reference_time is not None:
        gap = pd.Timedelta(hours=exclude_within_hours)
        stamp = pd.Timestamp(reference_time)
        table = table.loc[(table.index < stamp - gap) | (table.index > stamp + gap)]
    if len(table) < k:
        raise ValueError("Недостаточно доступной истории для поиска похожих ситуаций")
    values, centre, scale = _matrix(table, columns)
    point = np.array([dict(current).get(c, np.nan) for c in columns], float)
    if not np.isfinite(point).all():
        raise ValueError("Текущее состояние описано не полностью; похожие ситуации не ищутся")
    distance = np.linalg.norm((values - centre) / scale - (point - centre) / scale, axis=1)
    separation = pd.Timedelta(hours=min_separation_hours)
    chosen: list[int] = []
    for position in np.argsort(distance):
        when = table.index[position]
        if any(abs(when - table.index[taken]) < separation for taken in chosen):
            continue
        chosen.append(position)
        if len(chosen) == k:
            break
    if not chosen:
        raise ValueError("Не нашлось независимых по времени похожих ситуаций")
    return pd.DataFrame({"distance": distance[chosen]},
                        index=table.index[chosen]).sort_values("distance")


def outcomes(twins: pd.DataFrame, target: pd.Series, horizon_hours: float,
             tolerance_minutes: float = 30) -> pd.DataFrame:
    """What the target did over the horizon after each twin moment."""
    target = target.sort_index()
    tolerance = pd.Timedelta(minutes=tolerance_minutes)
    start = target.reindex(twins.index, method="nearest", tolerance=tolerance)
    later = target.reindex(twins.index + pd.Timedelta(hours=horizon_hours),
                           method="nearest", tolerance=tolerance)
    return pd.DataFrame({
        "time": twins.index, "distance": twins.distance.to_numpy(),
        "target_now": start.to_numpy(), "target_later": later.to_numpy(),
        "change": later.to_numpy() - start.to_numpy(),
    }).dropna(subset=["target_later"]).reset_index(drop=True)


def summarise(result: pd.DataFrame, limit: float) -> dict:
    if result.empty:
        return {"twins": 0, "usable": False, "reason": "Ни у одной похожей ситуации нет известного исхода"}
    return {
        "twins": int(len(result)),
        "usable": bool(len(result) >= 10),
        "median_target_later": float(result.target_later.median()),
        "median_change": float(result.change.median()),
        "share_above_limit": float((result.target_later > limit).mean()),
        "worst_target_later": float(result.target_later.max()),
        "dates": [str(t) for t in result.time.head(10)],
        "reason": f"В {len(result)} похожих ситуациях показатель через горизонт был выше предела "
                  f"в {(result.target_later > limit).mean():.0%} случаев",
        "scope": "Похожесть оценивается по выбранным тегам. Совпадение режима не гарантирует совпадения "
                 "неизмеренных условий, поэтому это свидетельство, а не прогноз.",
    }


def action_outcomes(history: pd.DataFrame, result: pd.DataFrame, tag: str, move_hours: float = 2,
                    min_group: int = 5) -> dict:
    """Split twins by the direction the tag was actually moved, then compare outcomes."""
    if tag not in history.columns or result.empty:
        return {"tag": tag, "usable": False, "reason": "Нет данных по тегу или похожих ситуаций"}
    series = history[tag].sort_index()
    tolerance = pd.Timedelta(minutes=30)
    times = pd.DatetimeIndex(result.time)
    before = series.reindex(times, method="nearest", tolerance=tolerance).to_numpy()
    after = series.reindex(times + pd.Timedelta(hours=move_hours), method="nearest",
                           tolerance=tolerance).to_numpy()
    move = after - before
    step = np.nanstd(np.diff(series.to_numpy(float)))
    threshold = float(step * 3) if np.isfinite(step) and step > 0 else 0.0
    groups = {}
    for name, mask in [("increased", move > threshold), ("decreased", move < -threshold),
                       ("held", np.abs(move) <= threshold)]:
        picked = result[mask & np.isfinite(move)]
        if len(picked) < min_group:
            continue
        groups[name] = {"cases": int(len(picked)), "median_change": float(picked.change.median()),
                        "median_target_later": float(picked.target_later.median()),
                        "dates": [str(t) for t in picked.time.head(5)]}
    return {
        "tag": tag, "move_hours": float(move_hours), "move_threshold": threshold,
        "groups": groups, "usable": len(groups) >= 2,
        "reason": "Сравнение возможно: в истории есть похожие ситуации с разным направлением изменения"
                  if len(groups) >= 2 else
                  "В похожих ситуациях тег почти не менялся по-разному; сравнить направления нельзя",
        "scope": "Оператор менял тег не случайно, поэтому разница между группами не является эффектом воздействия. "
                 "Это описание истории, проверяемое по указанным датам.",
    }
