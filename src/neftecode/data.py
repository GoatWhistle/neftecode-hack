"""Readers and causal features. Workbook pairs have independent time axes."""
from datetime import datetime
from pathlib import Path

import numpy as np
import openpyxl
import pandas as pd


def series_frame(records: list[tuple], name: str) -> pd.DataFrame:
    frame = pd.DataFrame(records, columns=["time", "value"])
    frame["time"] = pd.to_datetime(frame.time, errors="raise")
    frame["value"] = pd.to_numeric(frame.value, errors="coerce")
    if frame.time.isna().any() or not np.isfinite(frame.value).all():
        raise ValueError(f"{name}: некорректное время или значение измерения; источник требует проверки")
    if (frame.value < 0).any():
        raise ValueError(f"{name}: отрицательная сера, требуется разбор источника")
    if frame.groupby("time").value.nunique().gt(1).any():
        raise ValueError(f"{name}: противоречивые дубликаты времени")
    return frame.drop_duplicates("time").sort_values("time").reset_index(drop=True)


def load_sources(task: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    telemetry = []
    for filename, prefix in [("avt_tags.csv", "avt"), ("242000_tags.csv", "ht")]:
        frame = pd.read_csv(task / "data" / filename)
        frame = frame.loc[:, ~frame.columns.str.startswith("Unnamed:")]
        frame["date"] = pd.to_datetime(frame.date, errors="raise")
        if frame.date.duplicated().any():
            raise ValueError(f"{filename}: дубликаты времени")
        frame = frame.set_index("date").sort_index().astype(float)
        telemetry.append(frame.add_prefix(prefix + "."))
    # Prefixes prevent collisions between equally named AVT and HT sensors.
    signals = pd.concat(telemetry, axis=1).sort_index().replace([np.inf, -np.inf], np.nan)

    book = openpyxl.load_workbook(next(task.glob("ЛИМС*.xlsx")), read_only=True, data_only=True)
    rows = list(book.active.values)
    if rows[1][94] != "Mg.Sulfur" or rows[2][94] != "мг/кг":
        raise ValueError("ЛИМС CQ:CR: изменилась схема целевого показателя")
    lab = series_frame([(r[94], r[95]) for r in rows[4:] if isinstance(r[94], datetime)], "ЛИМС")
    book.close()

    book = openpyxl.load_workbook(next(task.glob("Выгрузка*.xlsx")), read_only=True, data_only=True)
    rows = iter(book.active.values)
    names, units = next(rows), next(rows)
    if "Mg.Sulfur" not in str(names[0]) or units[0] != "ppm":
        raise ValueError("ПАК A:B: изменилась схема серы")
    online = series_frame([(r[0], r[1]) for r in rows if isinstance(r[0], datetime)], "ПАК")
    book.close()
    return signals, lab, online


#: Bounds confirmed by the experts (messages 517 and 518). See context/requirements-map.md.
CASE_MAX_HORIZON_HOURS = 3.0
CASE_MAX_LAB_DELAY_HOURS = 4.0


def check_time_assumptions(cfg: dict) -> dict:
    """Refuse a configuration that quietly contradicts the confirmed case bounds.

    The history window used to build features is a different quantity from the forecast
    horizon; conflating them is what produced the earlier 6-hour settings.
    """
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
    """Join by availability, retaining sample time. Never backfill from the future."""
    if not np.isfinite(delay_hours) or delay_hours < 0:
        raise ValueError("Задержка доступности анализа не может быть отрицательной или неизвестной")
    left = pd.DataFrame({"decision_time": pd.to_datetime(times), "order": np.arange(len(times))})
    right = readings.rename(columns={"time": "sample_time"}).copy()
    right["available_time"] = right.sample_time + pd.Timedelta(hours=delay_hours)
    joined = pd.merge_asof(left.sort_values("decision_time"), right.sort_values("available_time"),
                           left_on="decision_time", right_on="available_time", direction="backward")
    return joined.sort_values("order").reset_index(drop=True)


def build_features(signals: pd.DataFrame, lab: pd.DataFrame, online: pd.DataFrame,
                   decisions, cfg: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    bounds = check_time_assumptions(cfg)
    window = bounds["history_window_hours"]
    suffix = f"{window:g}h"
    times = pd.DatetimeIndex(decisions)
    current = signals.reindex(times, method="ffill", tolerance=pd.Timedelta(minutes=20))
    old = signals.reindex(times - pd.Timedelta(hours=window), method="ffill", tolerance=pd.Timedelta(minutes=20))
    old.index = times
    # Time-based trailing windows, right closed. No centered windows/interpolation.
    # This window looks BACKWARD over available history; it is not the forecast horizon.
    mean = signals.rolling(suffix, min_periods=6).mean().reindex(
        times, method="ffill", tolerance=pd.Timedelta(minutes=20))
    x = pd.concat([current.add_suffix(".now"), mean.add_suffix(f".mean{suffix}"),
                   (current - old).add_suffix(f".delta{suffix}")], axis=1).reset_index(drop=True)
    latest_lab = backward_readings(times, lab, bounds["lab_delay_hours"])
    latest_pak = backward_readings(times, online)
    age_lab = (latest_lab.decision_time - latest_lab.sample_time).dt.total_seconds() / 3600
    age_pak = (latest_pak.decision_time - latest_pak.sample_time).dt.total_seconds() / 60

    p = online.set_index("time").value
    frozen = ((p.rolling("1h", min_periods=6).max() - p.rolling("1h", min_periods=6).min()) <= 1e-6)
    frozen = frozen.reindex(times, method="ffill", tolerance=pd.Timedelta(minutes=30)).fillna(False).to_numpy(bool)
    # Compare a known lab result with PAK at the SAME sample time, not with current PAK.
    aligned = latest_lab[["sample_time"]].copy()
    valid = aligned.sample_time.notna()
    pak_at_lab = np.full(len(times), np.nan)
    pak_at_lab[valid] = p.reindex(pd.DatetimeIndex(aligned.loc[valid, "sample_time"]),
                                method="ffill", tolerance=pd.Timedelta(minutes=30)).to_numpy()
    conflict = (np.abs(pak_at_lab - latest_lab.value) > np.maximum(3, .5 * latest_lab.value))
    lab_good = age_lab.le(cfg["lab_max_age_hours"]) & latest_lab.value.notna()
    conflict = conflict & lab_good
    pak_good = age_pak.le(cfg["pak_max_age_minutes"]) & ~frozen & ~conflict
    x["lab.sulfur"] = latest_lab.value.where(lab_good)
    x["lab.age_hours"] = age_lab
    x["pak.sulfur"] = latest_pak.value.where(pak_good)
    x["pak.age_minutes"] = age_pak
    x["pak.rejected"] = ~pak_good
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


def make_dataset(signals, lab, online, cfg):
    """One real laboratory analysis produces exactly one evaluation row.

    Rare analyses are never resampled onto the 10-minute telemetry grid: that would turn
    1 458 measurements into tens of thousands of dependent rows and inflate every metric.
    """
    bounds = check_time_assumptions(cfg)
    targets = lab.copy()
    targets["decision_time"] = targets.time - pd.Timedelta(hours=bounds["horizon_hours"])
    # Need a complete history window and no forecast origin beyond telemetry coverage.
    targets = targets.loc[
        (targets.decision_time >= signals.index.min() + pd.Timedelta(hours=bounds["history_window_hours"])) &
        (targets.decision_time <= signals.index.max())].reset_index(drop=True)
    if targets.time.duplicated().any():
        raise ValueError("Целевые анализы содержат повторяющееся время отбора: одна проба дала бы "
                         "несколько независимых строк оценки")
    x, meta = build_features(signals, lab, online, targets.decision_time, cfg)
    meta["target_time"] = targets.time
    meta["target_available_time"] = targets.time + pd.Timedelta(hours=bounds["lab_delay_hours"])
    meta["actual_sulfur"] = targets.value
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
