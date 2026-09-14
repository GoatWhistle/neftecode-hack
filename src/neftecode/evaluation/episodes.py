"""Evaluate analyzer excursions, batch proxies, margins and alarm lead time.

An instantaneous excursion of the online analyzer is evidence, not a violation.
This module separates short flickers from sustained excursions and reports both,
so an alarm rule is never tuned against a target it invented. The same duration
convention is used by every calculation in this module.
"""
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


#: One convention for every episode: each reading is taken to represent its own sampling
#: interval, so an episode of `n` readings lasts `n * step`. The earlier code gave a single
#: reading one interval but a run only the span between its first and last stamp, which made
#: short and long episodes incomparable. See context/idea-review.md, section 3.
DURATION_RULE = ("Длительность эпизода = число отсчётов, умноженное на типичный шаг ряда. "
                 "Каждый отсчёт представляет свой интервал опроса. Соглашение одно для эпизодов "
                 "любой длины; фактические моменты перехода в данных неизвестны.")


def sampling_step_hours(series: pd.Series) -> float:
    """Typical spacing of the record, used as the exposure of one reading."""
    if len(series) < 2:
        return 0.0
    step = series.index.to_series().diff().dropna()
    return float(np.median(step.dt.total_seconds()) / 3600) if len(step) else 0.0


def excursion_episodes(readings, limit: float, gap_tolerance_minutes: float = 30) -> pd.DataFrame:
    """Contiguous runs above the limit. A hole in the record ends the episode."""
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
    """Trailing batch proxy. Windows with thin coverage return NaN rather than a guess."""
    series = _as_series(readings)
    window = f"{int(round(window_hours * 60))}min"
    step = series.index.to_series().diff().median()
    expected = max(1, int(pd.Timedelta(value=window_hours, unit="h") / step)) if pd.notna(step) else 1
    mean = series.rolling(window, closed="right").mean()
    count = series.rolling(window, closed="right").count()
    return mean.where(count >= min_coverage * expected)


def violation_profile(readings, limit: float, windows=(1, 8, 24), sustained_hours: float = 4) -> dict:
    """The headline comparison: how much of the excursion time survives batch averaging."""
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
    """Label a decision time as risky when it falls inside a sustained excursion.

    Used only for reporting alongside the instantaneous label, never as a silent
    replacement of the laboratory target.
    """
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
    """Hours until the batch proxy reaches the limit, from trailing data only."""
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


def evaluate_margin(readings, at, cfg: dict) -> dict:
    """Adapter callable for infrastructure runtime; all inputs are supplied by the caller."""
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


def margin_series(readings, limit: float, batch_window_hours: float = 8,
                  slope_window_hours: float = 4, response_lag_hours: float = 2) -> pd.DataFrame:
    """Vectorised margin over the whole record, for measuring warning lead time.

    The slope is a finite difference of the batch proxy rather than a refitted
    regression: coarser than `trend_margin`, but computed identically at every point.
    """
    averaged = batch_average(readings, batch_window_hours)
    step = pd.Series(averaged.index).diff().median()
    back = max(1, int(round(pd.Timedelta(value=slope_window_hours, unit="h") / step)))
    slope = (averaged - averaged.shift(back)) / slope_window_hours
    with np.errstate(divide="ignore", invalid="ignore"):
        hours = (limit - averaged) / slope.where(slope > 0)
    frame = pd.DataFrame({"batch_sulfur": averaged, "slope_ppm_per_hour": slope,
                          "hours_to_limit": hours})
    # An alarm means the limit is reachable before a change could take effect.
    frame["alarm"] = (frame.batch_sulfur > limit) | (frame.hours_to_limit <= response_lag_hours)
    frame["alarm"] = frame.alarm.fillna(False)
    return frame


def alarm_events(stamps, rearm_hours: float = 1.0) -> pd.DatetimeIndex:
    """Collapse a run of consecutive alarm readings into the notifications an operator sees.

    A flag that stays raised for six hours is one alarm, not thirty-six. Counting timestamps
    as alarms was what made the earlier burden figures meaningless.
    """
    stamps = pd.DatetimeIndex(stamps).sort_values()
    if not len(stamps):
        return stamps
    gap = stamps.to_series().diff()
    starts = gap.isna() | (gap > pd.Timedelta(value=rearm_hours, unit="h"))
    return pd.DatetimeIndex(stamps[starts.to_numpy()])


def lead_times(readings, alarms, limit: float, sustained_hours: float = 4,
               max_lead_hours: float = 24, total_readings: int | None = None,
               rearm_hours: float = 1.0, alarm_period: tuple | None = None) -> dict:
    """How early the first alarm appeared before each sustained excursion.

    Four outcomes are kept apart instead of being merged into one "detected" count:

    * **early** — an alarm event before the episode started; only these carry a lead time;
    * **late** — the first alarm event appeared after the episode had already begun;
    * **missed** — no alarm event in the matching window at all;
    * **unknown** — the episode falls outside the alarm record, so nothing can be said.

    Each alarm event is assigned to at most one episode, earliest first, so one alarm can no
    longer be credited to several excursions.
    """
    episodes = classify_episodes(excursion_episodes(readings, limit), sustained_hours)
    episodes = episodes[episodes.kind == "sustained"].reset_index(drop=True)
    events = alarm_events(alarms, rearm_hours)
    used = np.zeros(len(events), bool)
    covered = np.zeros(len(events), bool)
    # The period the detector actually ran over. Absence of an alarm outside it is absence of
    # knowledge, not absence of risk, so those episodes become `unknown` rather than `missed`.
    if alarm_period is not None:
        record_start, record_end = pd.Timestamp(alarm_period[0]), pd.Timestamp(alarm_period[1])
    else:
        record_start = record_end = None
    rows = []
    for row in episodes.sort_values("start").itertuples():
        outside = record_start is not None and not (record_start <= row.start <= record_end)
        if outside:
            rows.append({"start": row.start, "duration_hours": row.duration_hours,
                         "outcome": "unknown", "lead_hours": None, "first_alarm": None})
            continue
        window = ((events >= row.start - pd.Timedelta(value=max_lead_hours, unit="h")) &
                  (events <= row.end) & ~used)
        covered |= ((events >= row.start - pd.Timedelta(value=max_lead_hours, unit="h")) & (events <= row.end))
        if not window.any():
            rows.append({"start": row.start, "duration_hours": row.duration_hours,
                         "outcome": "missed", "lead_hours": None, "first_alarm": None})
            continue
        index = int(np.argmax(window))
        used[index] = True
        first = events[index]
        lead = float((row.start - first).total_seconds() / 3600)
        rows.append({"start": row.start, "duration_hours": row.duration_hours,
                     "outcome": "early" if lead > 0 else "late",
                     "lead_hours": lead if lead > 0 else None,
                     "late_by_hours": None if lead > 0 else float(-lead),
                     "first_alarm": first})
    frame = pd.DataFrame(rows)
    counts = frame.outcome.value_counts().to_dict() if len(frame) else {}
    early = frame[frame.outcome == "early"] if len(frame) else frame
    return {
        "episodes": int(len(frame)),
        "early": int(counts.get("early", 0)),
        "late": int(counts.get("late", 0)),
        "missed": int(counts.get("missed", 0)),
        "unknown": int(counts.get("unknown", 0)),
        "median_lead_hours": float(early.lead_hours.median()) if len(early) else None,
        "max_lead_hours_seen": float(early.lead_hours.max()) if len(early) else None,
        "alarm_readings": int(len(pd.DatetimeIndex(alarms))),
        "alarm_events": int(len(events)),
        "rearm_hours": float(rearm_hours),
        "alarm_period": None if record_start is None else [str(record_start), str(record_end)],
        "alarm_events_outside_matching_windows": int((~covered).sum()),
        # Lead time alone is gamed by alarming constantly; burden must be read next to it.
        "alarm_events_per_early_episode": float(len(events) / len(early)) if len(early) else None,
        "alarm_reading_share_of_record": (float(len(pd.DatetimeIndex(alarms)) / total_readings)
                                          if total_readings else None),
        "per_episode": ([{**r, "start": str(r["start"]),
                          "first_alarm": None if r["first_alarm"] is None else str(r["first_alarm"])}
                         for r in rows] if rows else []),
        "scope": f"Устойчивым считается превышение дольше {sustained_hours:g} ч по единому соглашению "
                 f"о длительности ({DURATION_RULE}). Окно сопоставления {max_lead_hours:g} ч — "
                 "диагностический просмотр назад, а не горизонт прогноза. Каждое событие тревоги "
                 "засчитывается не более чем одному эпизоду. Упреждение считается только по ранним "
                 "срабатываниям; поздние и пропущенные показаны отдельно. Эпизод вне записи тревог "
                 "получает статус unknown, а не «пропущен». Событие вне окон сопоставления "
                 "не обязательно ошибочно. Число отсчётов с поднятым флагом не равно числу "
                 "уведомлений оператору.",
    }
