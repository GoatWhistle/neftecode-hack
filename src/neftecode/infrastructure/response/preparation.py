from __future__ import annotations

import math

import numpy as np
import pandas as pd


TEMPERATURE_TAG = "ht.T6"
FLOW_TAG = "ht.F9"
CORE_TAGS = ("ht.T6", "ht.T5", "ht.F9", "ht.P13", "ht.F2", "ht.T11")
HORIZON_H = 3.0
GUARD = pd.Timedelta(6, "h")
WINDOW_MONTHS = 12
ARX_LAGS = 24
STEP_HORIZON = 54
PLATEAU_STEPS = slice(17, 48)
MIN_ROWS = 5000
BOOT = 40
SEED = 0
WEAK_MULT = 0.5
STRONG_DEFAULT = 2.5
STRONG_CAP = -1.0
FEED_FLOOR_Q = 0.01
SCHEMA_VERSION = "v1"


def prepare(signals: pd.DataFrame, online: pd.DataFrame, feed_floor_until) -> pd.DataFrame:
    missing = [tag for tag in CORE_TAGS if tag not in signals.columns]
    if missing:
        raise ValueError(f"Для оценки отклика нет тегов {missing}")
    idx = signals.index
    f = pd.DataFrame(index=idx)
    f["T6"], f["T5"], f["F9"] = signals[TEMPERATURE_TAG], signals["ht.T5"], signals[FLOW_TAG]
    f["P13"], f["F2"] = signals["ht.P13"], signals["ht.F2"]
    hot = (f.T6 > 320) & (f.T5 > 320) & (f.P13 > 3.0) & (f.F2 > 30000) & (f.F9 > 0)
    if feed_floor_until is None:
        raise ValueError("prepare: нужен feed_floor_until (τ − 6 ч), иначе порог расхода учится на будущем")
    floor_rows = hot & (f.index <= pd.Timestamp(feed_floor_until))
    feed_floor = float(f.F9[floor_rows].quantile(FEED_FLOOR_Q)) if floor_rows.any() else math.nan
    running = hot & (f.F9 > feed_floor) & signals[list(CORE_TAGS)].notna().all(axis=1)
    f["running"] = running
    f.attrs["feed_floor"] = feed_floor
    f.attrs["feed_floor_until"] = pd.Timestamp(feed_floor_until).isoformat()
    r = running.astype(float)
    f["run_past12h"] = r.rolling("12h").min().eq(1)
    f["stable_label"] = f.run_past12h & r[::-1].rolling(37, min_periods=1).min()[::-1].eq(1)
    p = online.set_index("time").value.sort_index()
    changed = p.diff().abs().gt(1e-6) | p.diff().isna()
    run = changed.cumsum()
    t = p.index.to_series()
    frozen = (t - t.groupby(run).transform("min")) >= pd.Timedelta(1, "h")
    grid = lambda s, how: s.resample("10min", label="right", closed="right").agg(how).reindex(idx)
    pak = grid(p, "mean")
    fr = grid(frozen.astype(float), "max").fillna(1.0).astype(bool)
    f["pak"] = pak.where(~fr & pak.between(0.05, 50))
    return f


def _wmean(s: pd.Series, t: pd.DatetimeIndex, start_min: int, end_min: int, min_valid: int = 1):
    width = (end_min - start_min) // 10
    return s.rolling(width, min_periods=min_valid).mean().reindex(t + pd.Timedelta(end_min, "min")).to_numpy()


def decision_rows(f: pd.DataFrame, times: pd.DatetimeIndex) -> pd.DataFrame:
    d = pd.DataFrame(index=times)
    d["PAK30m"] = _wmean(f.pak, times, -30, 0, 1)
    d["PAK24h"] = _wmean(f.pak, times, -1440, 0, 72)
    d["T6"] = _wmean(f.T6, times, -30, 0, 1)
    d["F9"] = _wmean(f.F9, times, -30, 0, 1)
    d["A30"] = _wmean(f.T6, times, 0, 30, 1) - d.T6
    d["y3"] = _wmean(f.pak, times, 180, 210, 2)
    ok = np.ones(len(times), bool)
    for off in (-420, -60, 0, 30, 60, 120, 180, 210):
        ok &= f.stable_label.reindex(times + pd.Timedelta(off, "min")).fillna(False).to_numpy(bool)
    d["train_valid"] = ok & np.isfinite(d[["PAK30m", "PAK24h", "T6", "F9", "A30", "y3"]]).all(axis=1).to_numpy()
    return d


def row_times(f: pd.DataFrame) -> pd.DatetimeIndex:
    times = f.index[(f.index.minute % 30 == 0)]
    return times[(times >= times[0] + pd.Timedelta(31, "D")) & (times <= times[-1] - pd.Timedelta(4, "h"))]
