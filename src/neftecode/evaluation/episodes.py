import numpy as np
import pandas as pd

from .margins import (DURATION_RULE, _as_series, action_window, batch_average, classify_episodes,
                      evaluate_margin, excursion_episodes, sampling_step_hours, sustained_labels,
                      trend_margin, violation_profile)

__all__ = ["DURATION_RULE", "_as_series", "action_window", "alarm_events", "batch_average", "classify_episodes",
           "evaluate_margin", "excursion_episodes", "lead_times", "margin_series",
           "sampling_step_hours", "sustained_labels", "trend_margin", "violation_profile"]


def margin_series(readings, limit: float, batch_window_hours: float = 8,
                  slope_window_hours: float = 4, response_lag_hours: float = 2) -> pd.DataFrame:
    averaged = batch_average(readings, batch_window_hours)
    step = pd.Series(averaged.index).diff().median()
    back = max(1, int(round(pd.Timedelta(value=slope_window_hours, unit="h") / step)))
    slope = (averaged - averaged.shift(back)) / slope_window_hours
    with np.errstate(divide="ignore", invalid="ignore"):
        hours = (limit - averaged) / slope.where(slope > 0)
    frame = pd.DataFrame({"batch_sulfur": averaged, "slope_ppm_per_hour": slope,
                          "hours_to_limit": hours})
    frame["alarm"] = (frame.batch_sulfur > limit) | (frame.hours_to_limit <= response_lag_hours)
    frame["alarm"] = frame.alarm.fillna(False)
    return frame


def alarm_events(stamps, rearm_hours: float = 1.0) -> pd.DatetimeIndex:
    stamps = pd.DatetimeIndex(stamps).sort_values()
    if not len(stamps):
        return stamps
    gap = stamps.to_series().diff()
    starts = gap.isna() | (gap > pd.Timedelta(value=rearm_hours, unit="h"))
    return pd.DatetimeIndex(stamps[starts.to_numpy()])


def lead_times(readings, alarms, limit: float, sustained_hours: float = 4,
               max_lead_hours: float = 24, total_readings: int | None = None,
               rearm_hours: float = 1.0, alarm_period: tuple | None = None) -> dict:
    episodes = classify_episodes(excursion_episodes(readings, limit), sustained_hours)
    episodes = episodes[episodes.kind == "sustained"].reset_index(drop=True)
    events = alarm_events(alarms, rearm_hours)
    used = np.zeros(len(events), bool)
    covered = np.zeros(len(events), bool)
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
