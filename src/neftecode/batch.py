"""Specification applies to a blended batch, not to one 10-minute analyzer reading.

An instantaneous excursion of the online analyzer is evidence, not a violation.
This module separates short flickers from sustained excursions and reports both,
so an alarm rule is never tuned against a target it invented.
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


def excursion_episodes(readings, limit: float, gap_tolerance_minutes: float = 30) -> pd.DataFrame:
    """Contiguous runs above the limit. A hole in the record ends the episode."""
    series = _as_series(readings)
    above = series > limit
    if not above.any():
        return pd.DataFrame(columns=["start", "end", "duration_hours", "n_points", "peak", "mean"])
    step = series.index.to_series().diff()
    broken = step > pd.Timedelta(minutes=gap_tolerance_minutes)
    group = (above.ne(above.shift()) | broken).cumsum()
    rows = []
    for _, part in series[above].groupby(group[above]):
        span = (part.index[-1] - part.index[0]).total_seconds() / 3600
        # A single reading still occupies its own sampling interval.
        typical = np.median(step.dropna().dt.total_seconds()) / 3600 if len(series) > 1 else 0
        rows.append({"start": part.index[0], "end": part.index[-1],
                     "duration_hours": float(span if len(part) > 1 else typical),
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
    expected = max(1, int(pd.Timedelta(hours=window_hours) / step)) if pd.notna(step) else 1
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
