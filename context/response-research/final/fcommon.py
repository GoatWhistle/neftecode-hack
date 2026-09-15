"""Shared helpers for the final temperature-response study. Strict temporal protocol lives here.

SELECT  : target time < 2025-07-01 minus 6 h guard   (FIT < 2025-01-01, VAL 2025H1)
EVAL-1  : 2025H2      EVAL-2 : 2026
Nothing fitted, selected or calibrated may read EVAL rows. `select_frame` asserts it.
"""
import json
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from catboost import CatBoostRegressor  # noqa: E402

from common import OUT as OUT1, STATE, load  # noqa: E402,F401

OUT = HERE / "out"
OUT.mkdir(exist_ok=True)
G = pd.Timedelta("6h")
FIT_END = pd.Timestamp("2025-01-01")
SELECT_END = pd.Timestamp("2025-07-01")
EVAL1_END = pd.Timestamp("2026-01-01")
rng = np.random.default_rng(0)


def periods(target_time: pd.DatetimeIndex, decision_time: pd.DatetimeIndex | None = None) -> dict:
    t = pd.DatetimeIndex(target_time)
    d = t if decision_time is None else pd.DatetimeIndex(decision_time)
    return {
        "FIT": np.asarray(t < FIT_END - G),
        "VAL": np.asarray((d >= FIT_END + G) & (t < SELECT_END - G)),
        "SELECT": np.asarray(t < SELECT_END - G),
        "EVAL1": np.asarray((d >= SELECT_END + G) & (t < EVAL1_END - G)),
        "EVAL2": np.asarray(d >= EVAL1_END + G),
    }


def assert_select(target_time) -> None:
    tt = pd.DatetimeIndex(target_time)
    assert (tt < SELECT_END - G).all(), "LEAK: a SELECT-stage computation touched rows at or after 2025-07-01"


def cb(iterations=400, depth=5, lr=0.05, seed=0, **kw):
    return CatBoostRegressor(iterations=iterations, depth=depth, learning_rate=lr, random_seed=seed, thread_count=8,
                             verbose=False, allow_writing_files=False, **kw)


def crossfit(X: pd.DataFrame, y: np.ndarray, nblocks: int = 10, model=cb) -> np.ndarray:
    """Out-of-fold predictions over contiguous time blocks with a 1-day embargo (use on SELECT only)."""
    pred = np.full(len(X), np.nan)
    t = X.index
    for b in np.array_split(np.arange(len(X)), nblocks):
        lo, hi = t[b[0]] - pd.Timedelta("1d"), t[b[-1]] + pd.Timedelta("1d")
        tr = np.asarray((t < lo) | (t > hi))
        pred[b] = model().fit(X[tr], y[tr]).predict(X.iloc[b])
    return pred


def slope_ci(x, y, groups, draws=400, intercept=True):
    """OLS slope of y on x with group (week) block bootstrap 90% CI."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    ok = np.isfinite(x) & np.isfinite(y)
    x, y, groups = x[ok], y[ok], np.asarray(groups)[ok]

    def fit(ix):
        xx, yy = x[ix], y[ix]
        if intercept:
            xx = xx - xx.mean(); yy = yy - yy.mean()
        v = (xx * xx).sum()
        return (xx * yy).sum() / v if v > 0 else np.nan
    est = fit(np.arange(len(x)))
    ug = np.unique(groups)
    idx = {g: np.flatnonzero(groups == g) for g in ug}
    bs = [fit(np.concatenate([idx[g] for g in rng.choice(ug, len(ug))])) for _ in range(draws)]
    return {"est": float(est), "lo": float(np.nanpercentile(bs, 5)), "hi": float(np.nanpercentile(bs, 95)), "n": int(len(x))}


def weeks(index) -> np.ndarray:
    return np.asarray(pd.DatetimeIndex(index).to_period("W").astype(str))


def dump(name: str, obj) -> None:
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=1, default=str))
