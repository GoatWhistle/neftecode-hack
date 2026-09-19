import numpy as np
import pandas as pd


CASE_MAX_HORIZON_HOURS = 3.0
CASE_MAX_LAB_DELAY_HOURS = 4.0


def check_time_assumptions(cfg: dict) -> dict:
    horizon = cfg.get("horizon_hours")
    if not isinstance(horizon, (int, float)) or not np.isfinite(horizon) or not 0 < horizon <= CASE_MAX_HORIZON_HOURS:
        raise ValueError(f"horizon_hours: горизонт прогноза должен быть в пределах (0, {CASE_MAX_HORIZON_HOURS:g}] "
                         f"часов по уточнению эксперта, получено {horizon!r}")
    delay = cfg.get("lab_delay_hours")
    if not isinstance(delay, (int, float)) or not np.isfinite(delay) or delay < 0:
        raise ValueError(f"lab_delay_hours: задержка выдачи ЛИМС должна быть конечной и неотрицательной, получено {delay!r}")
    if delay > CASE_MAX_LAB_DELAY_HOURS:
        raise ValueError(f"lab_delay_hours: {delay} ч больше названного экспертом предела "
                         f"{CASE_MAX_LAB_DELAY_HOURS:g} ч; удлинять задержку без основания нельзя")
    window = cfg.get("history_window_hours")
    if not isinstance(window, (int, float)) or not np.isfinite(window) or window <= 0:
        raise ValueError(f"history_window_hours: окно прошлых признаков должно быть положительным, получено {window!r}")
    return {"horizon_hours": float(horizon), "lab_delay_hours": float(delay),
            "history_window_hours": float(window)}


def backward_readings(times, readings: pd.DataFrame, delay_hours: float = 0) -> pd.DataFrame:
    if not np.isfinite(delay_hours) or delay_hours < 0:
        raise ValueError("Задержка доступности анализа не может быть отрицательной или неизвестной")
    left = pd.DataFrame({"decision_time": pd.to_datetime(times), "order": np.arange(len(times))})
    right = readings.rename(columns={"time": "sample_time"}).copy()
    right["available_time"] = right.sample_time + pd.Timedelta(value=delay_hours, unit="h")
    joined = pd.merge_asof(left.sort_values("decision_time"), right.sort_values("available_time"),
                           left_on="decision_time", right_on="available_time", direction="backward")
    return joined.sort_values("order").reset_index(drop=True)


FROZEN_FORECAST_SELECTION = {
    "method": "preregistered_rolling_v1",
    "selected_before_2026": True,
    "selected": "last_pak_bc",
    "baseline": "last_pak",
    "bias_window_pairs": 20,
    "min_pairs": 5,
    "development_end": "2026-01-01",
    "evidence": "context/forecast-research/rolling-f4.json",
    "evidence_sha256": "ef83c7a0d8f8513886c9934c98ce08e2606df34c6715bd7908c545f3b2c1f627",
}


def validate_forecast_selection(cfg: dict) -> dict | None:
    selection = cfg.get("forecast_selection")
    if selection is None:
        return None
    mismatches = [key for key, expected in FROZEN_FORECAST_SELECTION.items()
                  if selection.get(key) != expected]
    if mismatches:
        raise ValueError("Production-выбор прогноза не совпадает с замороженным протоколом: "
                         + ", ".join(mismatches))
    return selection


def causal_pak_lab_bias(times, lab: pd.DataFrame, online: pd.DataFrame,
                        delay_hours: float, window: int = 20, min_pairs: int = 5) -> np.ndarray:
    """Оценивает причинную поправку прогноза ЛИМС по прошлым парам ЛИМС–ПАК.

    Это не приведение заводского ПАК к шкале ЛИМС. Часть разности может быть вызвана тем,
    что истинный момент отбора лабораторной пробы отличается от регламентного (ответ 18.09.2026).
    """
    if not isinstance(window, int) or not isinstance(min_pairs, int) \
            or min_pairs < 1 or window < min_pairs:
        raise ValueError("Окно поправки должно быть целым и не меньше минимального числа пар")
    if not np.isfinite(delay_hours) or delay_hours < 0:
        raise ValueError("Задержка доступности анализа не может быть отрицательной или неизвестной")
    decisions = pd.DataFrame({
        "decision_time": pd.DatetimeIndex(pd.to_datetime(times)).as_unit("ns"),
        "order": np.arange(len(times)),
    })
    if decisions.empty:
        return np.array([], dtype=float)

    pak = online.set_index("time").value.sort_index()
    pak.index = pd.DatetimeIndex(pak.index).as_unit("ns")
    sample_times = pd.DatetimeIndex(lab.time).as_unit("ns")
    pak_at_sample = pak.reindex(
        sample_times, method="ffill", tolerance=np.timedelta64(30, "m"),
    ).to_numpy(float)
    pairs = pd.DataFrame({
        "available_time": sample_times + np.timedelta64(round(delay_hours * 3600), "s"),
        "bias": lab.value.to_numpy(float) - pak_at_sample,
    })
    pairs = pairs.loc[np.isfinite(pairs.bias)].sort_values("available_time").reset_index(drop=True)
    if pairs.empty:
        return np.zeros(len(decisions), dtype=float)
    pairs["correction"] = pairs.bias.rolling(window, min_periods=min_pairs).median()
    joined = pd.merge_asof(
        decisions.sort_values("decision_time"),
        pairs[["available_time", "correction"]],
        left_on="decision_time",
        right_on="available_time",
        direction="backward",
    )
    return joined.sort_values("order").correction.fillna(0.0).to_numpy(float)
