import numpy as np
import pandas as pd


def _as_series(readings) -> pd.Series:
    if isinstance(readings, pd.Series):
        series = readings.copy()
    else:
        series = pd.Series(np.asarray(readings.value, float),
                           index=pd.DatetimeIndex(readings.time))
    if not series.index.is_monotonic_increasing:
        series = series.sort_index()
    if series.index.has_duplicates:
        raise ValueError("Дубликаты времени в ряду анализатора")
    return series.astype(float)


DURATION_RULE = ("Длительность эпизода = число отсчётов, умноженное на типичный шаг ряда. "
                 "Каждый отсчёт представляет свой интервал опроса. Соглашение одно для эпизодов "
                 "любой длины; фактические моменты перехода в данных неизвестны.")


def sampling_step_hours(series: pd.Series) -> float:
    if len(series) < 2:
        return 0.0
    step = series.index.to_series().diff().dropna()
    return float(np.median(step.dt.total_seconds()) / 3600) if len(step) else 0.0


def excursion_episodes(readings, limit: float, gap_tolerance_minutes: float = 30) -> pd.DataFrame:
    series = _as_series(readings)
    above = series > limit
    if not above.any():
        return pd.DataFrame(columns=["start", "end", "duration_hours", "n_points", "peak", "mean"])
    step = series.index.to_series().diff()
    broken = step > pd.Timedelta(value=gap_tolerance_minutes, unit="m")
    group = (above.ne(above.shift()) | broken).cumsum()
    typical = sampling_step_hours(series)
    rows = []
    for _, part in series[above].groupby(group[above]):
        rows.append({"start": part.index[0], "end": part.index[-1],
                     "duration_hours": float(len(part) * typical),
                     "span_hours": float((part.index[-1] - part.index[0]).total_seconds() / 3600),
                     "n_points": int(len(part)), "peak": float(part.max()), "mean": float(part.mean())})
    return pd.DataFrame(rows).sort_values("start").reset_index(drop=True)


def classify_episodes(episodes: pd.DataFrame, sustained_hours: float) -> pd.DataFrame:
    if sustained_hours <= 0:
        raise ValueError("Порог длительности устойчивого превышения должен быть положительным")
    out = episodes.copy()
    out["kind"] = np.where(out.duration_hours >= sustained_hours, "sustained", "flicker")
    return out


def batch_average(readings, window_hours: float, min_coverage: float = .5) -> pd.Series:
    series = _as_series(readings)
    window = f"{int(round(window_hours * 60))}min"
    step = series.index.to_series().diff().median()
    expected = max(1, int(pd.Timedelta(value=window_hours, unit="h") / step)) if pd.notna(step) else 1
    mean = series.rolling(window, closed="right").mean()
    count = series.rolling(window, closed="right").count()
    return mean.where(count >= min_coverage * expected)


def violation_profile(readings, limit: float, windows=(1, 8, 24), sustained_hours: float = 4) -> dict:
    series = _as_series(readings)
    episodes = classify_episodes(excursion_episodes(series, limit), sustained_hours)
    flicker = episodes[episodes.kind == "flicker"]
    sustained = episodes[episodes.kind == "sustained"]
    profile = {
        "limit": float(limit),
        "n_readings": int(len(series)),
        "instant_exceedance_share": float((series > limit).mean()),
        "episodes": int(len(episodes)),
        "flicker_episodes": int(len(flicker)),
        "sustained_episodes": int(len(sustained)),
        "sustained_hours_threshold": float(sustained_hours),
        "duration_rule": DURATION_RULE,
        "median_episode_hours": float(episodes.duration_hours.median()) if len(episodes) else None,
        "flicker_share_of_episodes": float(len(flicker) / len(episodes)) if len(episodes) else None,
        "hours_in_flickers": float(flicker.duration_hours.sum()),
        "hours_in_sustained": float(sustained.duration_hours.sum()),
        "windows": {},
        "scope": "Ряд ПАК. Окно — скользящее среднее назад, прокси партии. Настоящий состав партий в пакете не задан.",
    }
    for hours in windows:
        averaged = batch_average(series, hours)
        known = averaged.notna()
        profile["windows"][f"{hours}h"] = {
            "covered_share": float(known.mean()),
            "exceedance_share": float((averaged[known] > limit).mean()) if known.any() else None,
        }
    return profile


def sustained_labels(times, readings, limit: float, sustained_hours: float) -> np.ndarray:
    episodes = classify_episodes(excursion_episodes(readings, limit), sustained_hours)
    episodes = episodes[episodes.kind == "sustained"]
    stamps = pd.DatetimeIndex(times)
    label = np.zeros(len(stamps), bool)
    for row in episodes.itertuples():
        label |= (stamps >= row.start) & (stamps <= row.end)
    return label
def trend_margin(readings, at, limit: float, window_hours: float = 8,
                 batch_window_hours: float = 8, max_horizon_hours: float = 24,
                 min_points: int = 12) -> dict:
    when = pd.Timestamp(at)
    averaged = batch_average(readings, batch_window_hours)
    history = averaged.loc[(averaged.index > when - pd.Timedelta(value=window_hours, unit="h")) &
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


def evaluate_margin(readings, at, cfg: dict) -> dict:
    reading = trend_margin(
        readings,
        at,
        cfg["sulfur_limit"],
        cfg["margin_trend_window_hours"],
        cfg["batch_window_hours"],
        cfg["margin_max_horizon_hours"],
    )
    reading["window"] = action_window(reading, cfg["response_lag_hours"])
    return reading
