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


#: Exactly this value is a polling stub, not a measurement. The experts confirmed it (chat, message 582,
#: 2026-09-16: "307 — это выброс"); in the data it appears simultaneously in dozens of tags, including ones
#: whose physical range excludes it (a sulfur analyser around 8 ppm, a separator at 35 °C).
STUB_VALUE = 307.0
#: A telemetry column that is a stub more often than this is not measured at all and is dropped.
DEAD_COLUMN_STUB_SHARE = 0.9


def mask_stubs(signals: pd.DataFrame, until=None) -> tuple[pd.DataFrame, list[str]]:
    """Replace polling stubs by missing values and drop columns that never carry a measurement.

    With `until` the stub share is measured on the rows before it only (the training period), so the
    choice of columns does not look at later data. Without it the whole frame is used (synthetic tests).
    """
    masked = signals.mask(signals == STUB_VALUE)
    basis = signals if until is None else signals[signals.index < pd.Timestamp(until)]
    if basis.empty:
        raise ValueError("Нет строк телеметрии до границы отбора мёртвых колонок")
    dead = [c for c in masked.columns if (basis[c] == STUB_VALUE).mean() > DEAD_COLUMN_STUB_SHARE]
    return masked.drop(columns=dead), dead


def load_sources(task: Path, dead_until=None) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Read the four sources. `dead_until` — end of the training period (cfg["train_end"]) for `mask_stubs`."""
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
    signals, _ = mask_stubs(signals, dead_until)

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
    right["available_time"] = right.sample_time + pd.Timedelta(value=delay_hours, unit="h")
    joined = pd.merge_asof(left.sort_values("decision_time"), right.sort_values("available_time"),
                           left_on="decision_time", right_on="available_time", direction="backward")
    return joined.sort_values("order").reset_index(drop=True)


def build_features(signals: pd.DataFrame, lab: pd.DataFrame, online: pd.DataFrame,
                   decisions, cfg: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    bounds = check_time_assumptions(cfg)
    window = bounds["history_window_hours"]
    suffix = f"{window:g}h"
    times = pd.DatetimeIndex(decisions)
    current = signals.reindex(times, method="ffill", tolerance=pd.Timedelta(value=20, unit="m"))
    old = signals.reindex(times - pd.Timedelta(value=window, unit="h"), method="ffill", tolerance=pd.Timedelta(value=20, unit="m"))
    old.index = times
    # Time-based trailing windows, right closed. No centered windows/interpolation.
    # This window looks BACKWARD over available history; it is not the forecast horizon.
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
    # Compare a known lab result with PAK at the SAME sample time, not with current PAK.
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
    """One real laboratory analysis produces exactly one evaluation row.

    Rare analyses are never resampled onto the 10-minute telemetry grid: that would turn
    1 458 measurements into tens of thousands of dependent rows and inflate every metric.

    `target_lab` lets another laboratory series be the target while the features keep coming
    from the sulfur sources. The leak guard below then compares the right pair of times.
    """
    bounds = check_time_assumptions(cfg)
    targets = (lab if target_lab is None else target_lab).copy()
    targets["decision_time"] = targets.time - pd.Timedelta(value=bounds["horizon_hours"], unit="h")
    # Need a complete history window and no forecast origin beyond telemetry coverage.
    targets = targets.loc[
        (targets.decision_time >= signals.index.min() + pd.Timedelta(value=bounds["history_window_hours"], unit="h")) &
        (targets.decision_time <= signals.index.max())].reset_index(drop=True)
    if targets.time.duplicated().any():
        raise ValueError("Целевые анализы содержат повторяющееся время отбора: одна проба дала бы "
                         "несколько независимых строк оценки")
    x, meta = build_features(signals, lab, online, targets.decision_time, cfg)
    if target_lab is not None:
        # Persistence of the SAME property. Comparing a T95 model against the last sulfur
        # reading would be a straw man, not a baseline.
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


#: How far back the decision state carries quality history for tank-level estimates.
QUALITY_HISTORY_HOURS = 72
#: Legacy rules, used only when a configuration carries no rules derived from the data
#: (old model bundles and synthetic tests): 6 identical readings, conflict above max(3; 0.5·LIMS).
LEGACY_FROZEN_READINGS = 6
DEFAULT_PAK_PERIOD_MINUTES = 10.0


def frozen_rule(cfg: dict) -> tuple[int, float]:
    """How many identical consecutive analyser readings mean a frozen instrument, and the reading period."""
    readings = int(cfg.get("pak_frozen_readings", LEGACY_FROZEN_READINGS))
    period = float(cfg.get("pak_period_minutes", DEFAULT_PAK_PERIOD_MINUTES))
    if readings < 2 or not np.isfinite(period) or period <= 0:
        raise ValueError("pak_frozen_readings >= 2 и pak_period_minutes > 0 обязательны")
    return readings, period


def conflict_mask(pak_at_lab, lab_value, cfg: dict):
    """PAK disagrees with the laboratory result of the same sample by more than the declared threshold."""
    difference = np.abs(np.asarray(pak_at_lab, dtype=float) - np.asarray(lab_value, dtype=float))
    threshold = cfg.get("pak_conflict_mgkg")
    if threshold is None:
        return difference > np.maximum(3, .5 * np.asarray(lab_value, dtype=float))
    return difference > float(threshold)


def _untrusted_runs(values: pd.Series, cfg: dict | None = None) -> pd.Series:
    """Mark readings inside a flat run of at least the frozen number of readings, as far as known by now."""
    if values.empty:
        return pd.Series(dtype=bool)
    readings, _ = frozen_rule(cfg or {})
    changed = values.diff().abs().gt(1e-6) | values.diff().isna()
    run = changed.cumsum()
    return run.groupby(run).transform("size").ge(readings)


def derive_source_rules(signals: pd.DataFrame, lab: pd.DataFrame, online: pd.DataFrame, until,
                        cfg: dict) -> dict:
    """Source-trust thresholds computed from the training period only, with the method written down.

    The brief requires checks of completeness, freshness and consistency but gives no numbers, and the
    experts gave none either (except the laboratory delay). Each threshold is therefore a declared
    statistic of the history before `until`:

    * laboratory result stale after `lab_age_intervals` typical sampling intervals;
    * analyser reading stale after `pak_age_periods` typical polling periods;
    * analyser frozen after the number of identical consecutive readings that a live analyser reaches in
      no more than `frozen_run_rarity` of its runs;
    * analyser in conflict with the laboratory above the `conflict_quantile` of their absolute difference
      at the sample time;
    * telemetry incomplete from the rarest number of simultaneously missing sensors between the normal mode and
      the mode of simultaneous polling failures (the valley of the histogram).
    """
    method = {"lab_age_intervals": 2, "pak_age_periods": 3, "frozen_run_rarity": 0.001,
              "conflict_quantile": 0.95, "missing_rule": "histogram_valley", **cfg.get("source_rule_method", {})}
    until = pd.Timestamp(until)
    lab_part = lab[lab.time < until].sort_values("time")
    pak_part = online[online.time < until].sort_values("time")
    if len(lab_part) < 10 or len(pak_part) < 100:
        raise ValueError("Недостаточно истории для вывода порогов доверия к источникам")
    lab_interval = float(lab_part.time.diff().dt.total_seconds().dropna().median() / 3600)
    pak_period = float(pak_part.time.diff().dt.total_seconds().dropna().median() / 60)

    values = pak_part.set_index("time").value
    changed = values.diff().abs().gt(1e-6) | values.diff().isna()
    runs = values.groupby(changed.cumsum()).size()
    frozen_readings = 2
    while (runs >= frozen_readings).mean() > method["frozen_run_rarity"]:
        frozen_readings += 1

    joined = pd.merge_asof(lab_part, pak_part.rename(columns={"value": "pak"}), on="time", direction="backward",
                           tolerance=pd.Timedelta(value=pak_period * method["pak_age_periods"], unit="m")).dropna()
    conflict = float((joined.pak - joined.value).abs().quantile(method["conflict_quantile"]))

    telemetry = signals[signals.index < until]
    missing_counts = telemetry.isna().sum(axis=1).value_counts().reindex(range(telemetry.shape[1] + 1), fill_value=0)
    normal_mode = int(missing_counts.idxmax())
    largest = int(missing_counts[missing_counts > 0].index.max())
    # Simultaneous polling failures form the peak in the upper half of the observed range.
    upper = missing_counts.loc[max(normal_mode + 2, largest // 2):largest]
    outage_mode = int(upper.idxmax()) if len(upper) else largest + 1
    gap = missing_counts.loc[normal_mode + 1:max(normal_mode + 1, outage_mode - 1)]
    valley = int(gap.idxmin())
    missing = (valley - 1) / telemetry.shape[1]
    return {
        "lab_max_age_hours": round(method["lab_age_intervals"] * lab_interval, 3),
        "pak_max_age_minutes": round(method["pak_age_periods"] * pak_period, 3),
        "pak_period_minutes": round(pak_period, 3),
        "pak_frozen_readings": int(frozen_readings),
        "pak_conflict_mgkg": round(conflict, 3),
        "telemetry_max_missing_fraction": round(missing, 4),
        "source_rules": {
            "derived_until": until.isoformat(), "method": method,
            "observed": {"lab_median_interval_hours": lab_interval, "pak_median_period_minutes": pak_period,
                         "lab_samples": int(len(lab_part)), "paired_samples": int(len(joined)),
                         "pak_runs": int(len(runs)), "telemetry_rows": int(len(telemetry)),
                         "telemetry_columns": int(telemetry.shape[1]), "missing_normal_mode": normal_mode,
                         "missing_outage_mode": outage_mode, "missing_valley": valley},
            "note": ("Пороги выведены из истории до конца обучающего периода по объявленному методу; "
                     "организаторы численных порогов не давали."),
        },
    }


def recent_quality_history(lab: pd.DataFrame, online: pd.DataFrame, when, cfg: dict) -> dict:
    """Quality readings available at `when` over the last QUALITY_HISTORY_HOURS, as plain JSON values.

    Only what was known at `when`: analyser readings up to `when`, laboratory results whose
    availability (sample time plus the declared delay) is not later than `when`.
    """
    bounds = check_time_assumptions(cfg)
    when = pd.Timestamp(when)
    start = when - pd.Timedelta(value=QUALITY_HISTORY_HOURS, unit="h")
    p = online.set_index("time").value
    readings, period = frozen_rule(cfg)
    lookback = pd.Timedelta(value=readings * period, unit="m")
    part = p[(p.index > start - lookback) & (p.index <= when)]
    untrusted = _untrusted_runs(part, cfg)
    trusted = part[~untrusted & (part.index > start)]
    hourly = trusted.groupby(trusted.index.floor("h")).agg(["mean", "count"])
    steps = part.index.to_series().diff().dt.total_seconds().dropna()
    per_hour = float(3600 / steps.median()) if len(steps) and steps.median() > 0 else None
    available = lab.time + pd.Timedelta(value=bounds["lab_delay_hours"], unit="h")
    recent_lab = lab[(lab.time > start) & (available <= when)]
    known = part[~untrusted]
    return {
        "quality_history_hours": QUALITY_HISTORY_HOURS,
        "pak_last_trusted_value": float(known.iloc[-1]) if len(known) else None,
        "pak_last_trusted_time": known.index[-1].isoformat() if len(known) else None,
        "pak_trusted_hourly": [[t.isoformat(), float(row["mean"]), int(row["count"])]
                               for t, row in hourly.iterrows()],
        "pak_expected_per_hour": per_hour,
        "lab_recent": [[t.isoformat(), float(v)] for t, v in zip(recent_lab.time, recent_lab.value)],
    }
