import numpy as np
import pandas as pd

from .alignment import (CASE_MAX_HORIZON_HOURS, CASE_MAX_LAB_DELAY_HOURS, FROZEN_FORECAST_SELECTION,
                        backward_readings, causal_pak_lab_bias, check_time_assumptions,
                        validate_forecast_selection)
from .rules import (DEFAULT_PAK_PERIOD_MINUTES, LEGACY_FROZEN_READINGS, QUALITY_HISTORY_HOURS, conflict_mask,
                    derive_source_rules, frozen_rule, recent_quality_history, _untrusted_runs)
from .sources import DEAD_COLUMN_STUB_SHARE, STUB_VALUE, load_sources, mask_stubs, series_frame

__all__ = ["CASE_MAX_HORIZON_HOURS", "CASE_MAX_LAB_DELAY_HOURS", "DEAD_COLUMN_STUB_SHARE",
           "DEFAULT_PAK_PERIOD_MINUTES", "FROZEN_FORECAST_SELECTION", "LEGACY_FROZEN_READINGS",
           "QUALITY_HISTORY_HOURS", "STUB_VALUE", "backward_readings", "build_features",
           "causal_pak_lab_bias", "check_time_assumptions", "conflict_mask", "derive_source_rules",
           "frozen_rule", "load_sources", "make_dataset", "mask_stubs", "recent_quality_history",
           "series_frame", "split_periods", "validate_forecast_selection", "_untrusted_runs"]


def build_features(signals: pd.DataFrame, lab: pd.DataFrame, online: pd.DataFrame,
                   decisions, cfg: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    bounds = check_time_assumptions(cfg)
    window = bounds["history_window_hours"]
    suffix = f"{window:g}h"
    times = pd.DatetimeIndex(decisions)
    current = signals.reindex(times, method="ffill", tolerance=pd.Timedelta(value=20, unit="m"))
    old = signals.reindex(times - pd.Timedelta(value=window, unit="h"), method="ffill", tolerance=pd.Timedelta(value=20, unit="m"))
    old.index = times
    mean = signals.rolling(suffix, min_periods=6).mean().reindex(
        times, method="ffill", tolerance=pd.Timedelta(value=20, unit="m"))
    x = pd.concat([current.add_suffix(".now"), mean.add_suffix(f".mean{suffix}"),
                   (current - old).add_suffix(f".delta{suffix}")], axis=1).reset_index(drop=True)
    latest_lab = backward_readings(times, lab, bounds["lab_delay_hours"])
    latest_pak = backward_readings(times, online)
    age_lab = (latest_lab.decision_time - latest_lab.sample_time).dt.total_seconds() / 3600
    age_pak = (latest_pak.decision_time - latest_pak.sample_time).dt.total_seconds() / 60

    p = online.set_index("time").value
    readings, period = frozen_rule(cfg)
    window = pd.Timedelta(value=readings * period, unit="m")
    frozen = ((p.rolling(window, min_periods=readings).max()
               - p.rolling(window, min_periods=readings).min()) <= 1e-6)
    frozen = frozen.reindex(times, method="ffill", tolerance=pd.Timedelta(value=30, unit="m")).fillna(False).to_numpy(bool)
    aligned = latest_lab[["sample_time"]].copy()
    valid = aligned.sample_time.notna()
    pak_at_lab = np.full(len(times), np.nan)
    pak_at_lab[valid] = p.reindex(pd.DatetimeIndex(aligned.loc[valid, "sample_time"]),
                                method="ffill", tolerance=pd.Timedelta(value=30, unit="m")).to_numpy()
    conflict = conflict_mask(pak_at_lab, latest_lab.value, cfg)
    lab_good = age_lab.le(cfg["lab_max_age_hours"]) & latest_lab.value.notna()
    conflict = conflict & lab_good
    pak_good = age_pak.le(cfg["pak_max_age_minutes"]) & ~frozen & ~conflict
    x["lab.sulfur"] = latest_lab.value.where(lab_good)
    x["lab.age_hours"] = age_lab
    x["pak.sulfur"] = latest_pak.value.where(pak_good)
    x["pak.age_minutes"] = age_pak
    x["pak.rejected"] = ~pak_good
    forecast_selection = validate_forecast_selection(cfg)
    if forecast_selection:
        x["pak.lab_bias20"] = causal_pak_lab_bias(
            times,
            lab,
            online,
            bounds["lab_delay_hours"],
            window=forecast_selection["bias_window_pairs"],
            min_pairs=forecast_selection["min_pairs"],
        )
    meta = pd.DataFrame({
        "decision_time": times,
        "lab_sample_time": latest_lab.sample_time,
        "lab_available_time": latest_lab.available_time,
        "lab_value": latest_lab.value,
        "lab_age_hours": age_lab,
        "lab_usable": lab_good,
        "pak_sample_time": latest_pak.sample_time,
        "pak_available_time": latest_pak.available_time,
        "pak_value": latest_pak.value,
        "pak_age_minutes": age_pak,
        "pak_frozen": frozen,
        "pak_conflict": conflict,
        "pak_usable": pak_good,
        "telemetry_missing_fraction": current.isna().mean(axis=1).to_numpy(),
    })
    return x.astype(float), meta


def make_dataset(signals, lab, online, cfg, target_lab=None):
    bounds = check_time_assumptions(cfg)
    targets = (lab if target_lab is None else target_lab).copy()
    targets["decision_time"] = targets.time - pd.Timedelta(value=bounds["horizon_hours"], unit="h")
    targets = targets.loc[
        (targets.decision_time >= signals.index.min() + pd.Timedelta(value=bounds["history_window_hours"], unit="h")) &
        (targets.decision_time <= signals.index.max())].reset_index(drop=True)
    if targets.time.duplicated().any():
        raise ValueError("Целевые анализы содержат повторяющееся время отбора: одна проба дала бы "
                         "несколько независимых строк оценки")
    x, meta = build_features(signals, lab, online, targets.decision_time, cfg)
    if target_lab is not None:
        own = backward_readings(targets.decision_time, target_lab, bounds["lab_delay_hours"])
        own_age = (own.decision_time - own.sample_time).dt.total_seconds() / 3600
        x["lab.target"] = own.value.where(own_age.le(cfg["lab_max_age_hours"]) & own.value.notna()).to_numpy()
        x["lab.target_age_hours"] = own_age.to_numpy()
    meta["target_time"] = targets.time
    meta["target_available_time"] = targets.time + pd.Timedelta(value=bounds["lab_delay_hours"], unit="h")
    meta["actual_sulfur"] = targets.value
    meta["actual_target"] = targets.value
    leak = meta.lab_sample_time.notna() & (meta.lab_sample_time >= meta.target_time)
    if leak.any():
        raise ValueError(f"{int(leak.sum())} строк используют как признак пробу, взятую не раньше целевой; "
                         f"это утечка цели в признаки")
    return x, meta


def split_periods(meta: pd.DataFrame, cfg: dict) -> dict[str, np.ndarray]:
    a, b, c = [pd.Timestamp(cfg[k]) for k in ("train_end", "validation_end", "calibration_end")]
    if not a < b < c:
        raise ValueError("Границы периодов должны идти строго по возрастанию")
    return {
        "train": (meta.target_available_time < a).to_numpy(),
        "validation": ((meta.decision_time >= a) & (meta.target_available_time < b)).to_numpy(),
        "calibration": ((meta.decision_time >= b) & (meta.target_available_time < c)).to_numpy(),
        "test": (meta.decision_time >= c).to_numpy(),
    }
