"""Remaining margin instead of a bare alarm, and how early an alarm actually fired.

The operator question is not "is it bad now" but "how long do I have and when does
my window to act close". Extrapolation here is deliberately linear and short: a
longer forecast from this evidence would not be honest.
"""
import numpy as np
import pandas as pd

from .batch import batch_average, classify_episodes, excursion_episodes


def trend_margin(readings, at, limit: float, window_hours: float = 8,
                 batch_window_hours: float = 8, max_horizon_hours: float = 24,
                 min_points: int = 12) -> dict:
    """Hours until the batch proxy reaches the limit, from trailing data only."""
    when = pd.Timestamp(at)
    averaged = batch_average(readings, batch_window_hours)
    history = averaged.loc[(averaged.index > when - pd.Timedelta(hours=window_hours)) &
                           (averaged.index <= when)].dropna()
    result = {"at": when.isoformat(), "limit": float(limit), "points": int(len(history)),
              "window_hours": float(window_hours), "batch_window_hours": float(batch_window_hours),
              "max_horizon_hours": float(max_horizon_hours),
              "method": "линейный тренд по скользящему среднему назад; экстраполяция ограничена горизонтом"}
    if len(history) < min_points:
        return result | {"status": "unknown", "reason": "Слишком мало свежих измерений для оценки тренда"}
    hours = (history.index - when).total_seconds() / 3600
    slope, intercept = np.polyfit(hours, history.to_numpy(), 1)
    current = float(intercept)
    residual = float(np.std(history.to_numpy() - (slope * hours + intercept), ddof=2)) if len(history) > 2 else 0.0
    result.update(current_batch_sulfur=current, slope_ppm_per_hour=float(slope),
                  residual_ppm=residual, margin_ppm=float(limit - current))
    if current > limit:
        return result | {"status": "already_above", "hours_to_limit": 0.0,
                         "reason": "Скользящее среднее уже выше предела"}
    if slope <= 0:
        return result | {"status": "no_trend_to_limit",
                         "reason": "Тренд не направлен к пределу; оценка времени не выдается"}
    hours_to_limit = (limit - current) / slope
    # Scatter around the fit is carried into the estimate rather than hidden.
    optimistic = (limit - current + residual) / slope
    pessimistic = max(0.0, (limit - current - residual) / slope)
    if hours_to_limit > max_horizon_hours:
        return result | {"status": "beyond_horizon", "hours_to_limit": None,
                         "reason": f"При текущем тренде предел дальше {max_horizon_hours:g} ч; точная оценка не выдается"}
    return result | {"status": "approaching", "hours_to_limit": float(hours_to_limit),
                     "hours_to_limit_optimistic": float(min(optimistic, max_horizon_hours)),
                     "hours_to_limit_pessimistic": float(pessimistic),
                     "reason": "Скользящее среднее движется к пределу"}


def action_window(margin: dict, response_lag_hours: float) -> dict:
    """When the window to act closes: the effect of a change is not immediate."""
    if response_lag_hours < 0:
        raise ValueError("Запаздывание отклика не может быть отрицательным")
    hours = margin.get("hours_to_limit_pessimistic", margin.get("hours_to_limit"))
    if margin.get("status") not in ("approaching", "already_above") or hours is None:
        return {"closes_in_hours": None, "status": margin.get("status"),
                "response_lag_hours": float(response_lag_hours),
                "reason": "Окно не рассчитано: нет оценки времени до предела"}
    remaining = hours - response_lag_hours
    return {"closes_in_hours": float(remaining), "status": "closed" if remaining <= 0 else "open",
            "response_lag_hours": float(response_lag_hours),
            "reason": "Окно закрыто: отклик на изменение не успеет до предела" if remaining <= 0
                      else "Изменение режима еще успевает подействовать до предела"}


def margin_series(readings, limit: float, batch_window_hours: float = 8,
                  slope_window_hours: float = 4, response_lag_hours: float = 2) -> pd.DataFrame:
    """Vectorised margin over the whole record, for measuring warning lead time.

    The slope is a finite difference of the batch proxy rather than a refitted
    regression: coarser than `trend_margin`, but computed identically at every point.
    """
    averaged = batch_average(readings, batch_window_hours)
    step = pd.Series(averaged.index).diff().median()
    back = max(1, int(round(pd.Timedelta(hours=slope_window_hours) / step)))
    slope = (averaged - averaged.shift(back)) / slope_window_hours
    with np.errstate(divide="ignore", invalid="ignore"):
        hours = (limit - averaged) / slope.where(slope > 0)
    frame = pd.DataFrame({"batch_sulfur": averaged, "slope_ppm_per_hour": slope,
                          "hours_to_limit": hours})
    # An alarm means the limit is reachable before a change could take effect.
    frame["alarm"] = (frame.batch_sulfur > limit) | (frame.hours_to_limit <= response_lag_hours)
    frame["alarm"] = frame.alarm.fillna(False)
    return frame


def lead_times(readings, alarms, limit: float, sustained_hours: float = 4,
               max_lead_hours: float = 24, total_readings: int | None = None) -> dict:
    """How many hours before each sustained excursion the first alarm appeared.

    Reported together with alarm burden on purpose: a rule that alarms all the time
    scores a perfect lead time and is useless to an operator.
    """
    episodes = classify_episodes(excursion_episodes(readings, limit), sustained_hours)
    episodes = episodes[episodes.kind == "sustained"].reset_index(drop=True)
    stamps = pd.DatetimeIndex(alarms).sort_values()
    rows, matched = [], np.zeros(len(stamps), bool)
    for row in episodes.itertuples():
        window = (stamps >= row.start - pd.Timedelta(hours=max_lead_hours)) & (stamps <= row.end)
        matched |= window
        if not window.any():
            rows.append({"start": row.start, "duration_hours": row.duration_hours,
                         "detected": False, "lead_hours": None})
            continue
        first = stamps[window][0]
        rows.append({"start": row.start, "duration_hours": row.duration_hours, "detected": True,
                     "first_alarm": first,
                     "lead_hours": float((row.start - first).total_seconds() / 3600)})
    frame = pd.DataFrame(rows)
    detected = frame[frame.detected] if len(frame) else frame
    early = detected[detected.lead_hours > 0] if len(detected) else detected
    return {
        "episodes": int(len(frame)),
        "detected": int(len(detected)),
        "detected_before_start": int(len(early)),
        "median_lead_hours": float(early.lead_hours.median()) if len(early) else None,
        "max_lead_hours_seen": float(early.lead_hours.max()) if len(early) else None,
        "alarms": int(len(stamps)),
        "alarms_outside_any_episode": int((~matched).sum()),
        # Lead time alone is gamed by alarming constantly; burden must be read next to it.
        "alarms_per_detected_episode": float(len(stamps) / len(detected)) if len(detected) else None,
        "alarm_share_of_record": float(len(stamps) / total_readings) if total_readings else None,
        "per_episode": frame.assign(
            start=frame.start.astype(str) if len(frame) else frame.get("start"),
            first_alarm=frame.first_alarm.astype(str) if "first_alarm" in frame else None,
        ).to_dict("records") if len(frame) else [],
        "scope": f"Устойчивым считается превышение дольше {sustained_hours:g} ч. "
                 f"Тревога засчитывается, если она не раньше чем за {max_lead_hours:g} ч до начала. "
                 "Упреждение читается только вместе с нагрузкой: правило, которое держит тревогу постоянно, "
                 "получает идеальное упреждение и бесполезно. Тревоги вне эпизодов не обязательно ошибочны.",
    }
