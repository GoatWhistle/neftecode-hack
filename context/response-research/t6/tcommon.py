"""Shared helpers for the T6/F9 re-estimation (copy of final/fcommon.py + own data cache).

Differences from final/: reactor-inlet temperature is ht.T6 (not T11), feed is ht.F9 mass t/h (not F26);
data are re-read with the current load_sources (307 -> NaN at load) into t6/out/cache.pkl.
Temporal protocol unchanged: SELECT target < 2025-07-01 − 6 h; EVAL1 2025H2; EVAL2 2026.
"""
import json
import pickle
import sys
import warnings
from datetime import datetime
from pathlib import Path

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE.parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from catboost import CatBoostRegressor  # noqa: E402

from common import LIMS_COLUMNS, _lims_extra  # noqa: E402
from neftecode.infrastructure.data.data import load_sources  # noqa: E402

OUT = HERE / "out"
OUT.mkdir(exist_ok=True)
CACHE = OUT / "cache.pkl"
G = pd.Timedelta("6h")
FIT_END = pd.Timestamp("2025-01-01")
SELECT_END = pd.Timestamp("2025-07-01")
EVAL1_END = pd.Timestamp("2026-01-01")
rng = np.random.default_rng(0)
T_IN, FEED = "ht.T6", "ht.F9"


def load(refresh: bool = False):
    """signals (10-min, 307 already NaN), lab sulfur, online PAK, extra LIMS dict."""
    if CACHE.exists() and not refresh:
        with CACHE.open("rb") as s:
            return pickle.load(s)
    signals, lab, online = load_sources(ROOT / "task")
    extra = _lims_extra(ROOT / "task")
    data = (signals, lab, online, extra)
    with CACHE.open("wb") as s:
        pickle.dump(data, s)
    return data


def periods(target_time, decision_time=None) -> dict:
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
    pred = np.full(len(X), np.nan)
    t = X.index
    for b in np.array_split(np.arange(len(X)), nblocks):
        lo, hi = t[b[0]] - pd.Timedelta("1d"), t[b[-1]] + pd.Timedelta("1d")
        tr = np.asarray((t < lo) | (t > hi))
        pred[b] = model().fit(X[tr], y[tr]).predict(X.iloc[b])
    return pred


def slope_ci(x, y, groups, draws=400, intercept=True):
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


# ---- ARX plateau on a frame with columns T_in, feed, pak, stable (same maths as final/f6–f8, response_model.arx_plateau)
L = 24


def arx_design(f: pd.DataFrame, t_col: str = "T_in", f_col: str = "feed"):
    g10 = f[[t_col, f_col, "pak", "stable"]].copy(); g10["pak"] = g10.pak.rolling("30min").mean()
    D10 = g10[[t_col, f_col, "pak"]].diff()
    Xl = pd.concat({f"{c}_{j}": D10[c].shift(j) for c in [t_col, f_col, "pak"] for j in range(1, L + 1)}, axis=1)
    m = (g10.stable & g10.pak.notna() & g10.stable.shift(L, fill_value=False) & Xl.notna().all(axis=1) & D10.pak.notna()).to_numpy()
    return g10.index[m], Xl.to_numpy()[m], D10.pak.to_numpy()[m]


def step_response(coef, n=54):
    b, a = coef[:L], coef[2 * L:3 * L]
    u = np.zeros(n + L); u[L] = 1; ys = np.zeros(n + L)
    for t in range(L, n + L):
        ys[t] = b @ u[t - L:t][::-1] + a @ ys[t - L:t][::-1]
    return np.cumsum(ys[L:])


def plateau(T, Xm, ym, mask, boot=0, seed=0):
    from sklearn.linear_model import LinearRegression

    def one(ix):
        return float(step_response(LinearRegression().fit(Xm[ix], ym[ix]).coef_)[17:48].mean())
    ix = np.flatnonzero(mask)
    if len(ix) < 5000:
        return [np.nan, np.nan, np.nan, int(len(ix))] if boot else np.nan
    est = one(ix)
    if not boot:
        return est
    r = np.random.default_rng(seed)
    mon = np.asarray(T[ix].to_period("M").astype(str)); um = np.unique(mon); gi = {u: ix[mon == u] for u in um}
    bs = [one(np.concatenate([gi[u] for u in r.choice(um, len(um))])) for _ in range(boot)]
    return [est, float(np.percentile(bs, 5)), float(np.percentile(bs, 95)), int(len(ix))]


def halves(index):
    return np.asarray(pd.DatetimeIndex(index).year.astype(str)) + np.where(pd.DatetimeIndex(index).month <= 6, "H1", "H2")
