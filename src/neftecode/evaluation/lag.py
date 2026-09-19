import numpy as np
import pandas as pd


def _aligned(signals: pd.DataFrame, target: pd.Series) -> tuple[pd.DataFrame, pd.Series]:
    if not isinstance(target, pd.Series):
        target = pd.Series(np.asarray(target.value, float), index=pd.DatetimeIndex(target.time))
    target = target.sort_index()
    frame = signals.sort_index().join(target.rename("__target__"), how="inner")
    if len(frame) < 100:
        raise ValueError("Слишком короткое пересечение телеметрии и целевого ряда для оценки лага")
    return frame.drop(columns="__target__"), frame["__target__"]


def _steps(index: pd.DatetimeIndex, max_lag_hours: float, step_hours: float) -> tuple[list[int], pd.Timedelta]:
    spacing = pd.Series(index).diff().median()
    if pd.isna(spacing) or spacing <= pd.Timedelta(0):
        raise ValueError("Не удалось определить шаг ряда")
    stride = max(1, int(round(pd.Timedelta(value=step_hours, unit="h") / spacing)))
    top = int(round(pd.Timedelta(value=max_lag_hours, unit="h") / spacing))
    return list(range(0, top + 1, stride)), spacing


def lag_profile(signal: pd.Series, target: pd.Series, max_lag_hours: float = 24,
                step_hours: float = 1) -> pd.DataFrame:
    lags, spacing = _steps(signal.index, max_lag_hours, step_hours)
    rows = []
    for lag in lags:
        shifted = signal.shift(lag)
        both = shifted.notna() & target.notna()
        r = float(shifted[both].corr(target[both])) if both.sum() > 30 else np.nan
        rows.append({"lag_hours": lag * spacing.total_seconds() / 3600, "n": int(both.sum()), "r": r})
    return pd.DataFrame(rows)


def _best(values: np.ndarray, target: np.ndarray, lags: list[int]) -> tuple[int, float]:
    best_lag, best_r = 0, 0.0
    for lag in lags:
        if lag:
            a, b = values[:-lag], target[lag:]
        else:
            a, b = values, target
        good = np.isfinite(a) & np.isfinite(b)
        if good.sum() < 30:
            continue
        x, y = a[good], b[good]
        if x.std() < 1e-12 or y.std() < 1e-12:
            continue
        r = float(np.corrcoef(x, y)[0, 1])
        if abs(r) > abs(best_r):
            best_lag, best_r = lag, r
    return best_lag, best_r


def lag_map(signals: pd.DataFrame, target, max_lag_hours: float = 24, step_hours: float = 1,
            null_draws: int = 20, seed: int = 42) -> pd.DataFrame:
    frame, aligned_target = _aligned(signals, target)
    lags, spacing = _steps(frame.index, max_lag_hours, step_hours)
    y = aligned_target.to_numpy(float)
    rng = np.random.default_rng(seed)
    floor_offsets = rng.integers(len(y) // 4, 3 * len(y) // 4, size=null_draws)
    rows = []
    for column in frame.columns:
        values = frame[column].to_numpy(float)
        if not np.isfinite(values).any() or np.nanstd(values) < 1e-12:
            continue
        lag, r = _best(values, y, lags)
        null = [abs(_best(values, np.roll(y, int(offset)), lags)[1]) for offset in floor_offsets]
        rows.append({
            "tag": column,
            "best_lag_hours": lag * spacing.total_seconds() / 3600,
            "r_at_best_lag": r,
            "r_at_zero_lag": _best(values, y, [0])[1],
            "noise_floor_r": float(np.quantile(null, .95)) if null else np.nan,
            "above_noise_floor": bool(abs(r) > np.quantile(null, .95)) if null else False,
        })
    out = pd.DataFrame(rows)
    return out.reindex(out.r_at_best_lag.abs().sort_values(ascending=False).index).reset_index(drop=True)


def summarise(lag_table: pd.DataFrame) -> dict:
    real = lag_table[lag_table.above_noise_floor]
    return {
        "tags": int(len(lag_table)),
        "tags_above_noise_floor": int(len(real)),
        "median_lag_hours_above_floor": float(real.best_lag_hours.median()) if len(real) else None,
        "strongest": real.head(8)[["tag", "best_lag_hours", "r_at_best_lag", "noise_floor_r"]].to_dict("records")
                     if len(real) else [],
        "scope": "Корреляция при сдвиге — не доказательство причинной связи и не модель эффекта управления. "
                 "Порог шума получен повторным поиском лучшего лага на заведомо смещенной цели.",
    }
