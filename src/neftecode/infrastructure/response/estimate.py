from __future__ import annotations

import math

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

from .preparation import (ARX_LAGS, BOOT, CORE_TAGS, FEED_FLOOR_Q, FLOW_TAG, GUARD, HORIZON_H, MIN_ROWS,
                          PLATEAU_STEPS, SCHEMA_VERSION, SEED, STEP_HORIZON, STRONG_CAP, STRONG_DEFAULT,
                          TEMPERATURE_TAG, WEAK_MULT, WINDOW_MONTHS, _wmean, decision_rows, prepare,
                          row_times)

__all__ = ["ARX_LAGS", "BOOT", "CORE_TAGS", "FEED_FLOOR_Q", "FLOW_TAG", "GUARD", "HORIZON_H", "MIN_ROWS",
           "PLATEAU_STEPS", "SCHEMA_VERSION", "SEED", "STEP_HORIZON", "STRONG_CAP", "STRONG_DEFAULT",
           "TEMPERATURE_TAG", "WEAK_MULT", "WINDOW_MONTHS", "arx_design", "decision_rows", "drift",
           "_wmean", "estimate_response", "fit_at", "halves", "past_ratios", "plateau", "prepare", "response_at",
           "row_times", "step_response", "tau_grid"]


def arx_design(f: pd.DataFrame):
    g = pd.DataFrame({"T6": f.T6, "F9": f.F9, "pak": f.pak.rolling("30min").mean()})
    D = g.diff()
    X = pd.concat({f"{c}_{j}": D[c].shift(j) for c in ("T6", "F9", "pak") for j in range(1, ARX_LAGS + 1)}, axis=1)
    m = (f.stable_label & f.pak.notna() & f.stable_label.shift(ARX_LAGS, fill_value=False) & X.notna().all(axis=1)
         & D.pak.notna()).to_numpy()
    return f.index[m], X.to_numpy()[m], D.pak.to_numpy()[m]


def step_response(coef: np.ndarray) -> np.ndarray:
    b, a = coef[:ARX_LAGS], coef[2 * ARX_LAGS:3 * ARX_LAGS]
    u = np.zeros(STEP_HORIZON + ARX_LAGS)
    u[ARX_LAGS] = 1.0
    ys = np.zeros(STEP_HORIZON + ARX_LAGS)
    for k in range(ARX_LAGS, STEP_HORIZON + ARX_LAGS):
        ys[k] = b @ u[k - ARX_LAGS:k][::-1] + a @ ys[k - ARX_LAGS:k][::-1]
    return np.cumsum(ys[ARX_LAGS:])


def plateau(T: pd.DatetimeIndex, X: np.ndarray, y: np.ndarray, mask: np.ndarray, boot: int = 0, seed: int = SEED):
    def one(ix):
        return float(step_response(LinearRegression().fit(X[ix], y[ix]).coef_)[PLATEAU_STEPS].mean())
    ix = np.flatnonzero(mask)
    if len(ix) < MIN_ROWS:
        return math.nan, None, int(len(ix))
    est = one(ix)
    if not boot:
        return est, None, int(len(ix))
    rng = np.random.default_rng(seed)
    months = np.asarray(T[ix].to_period("M").astype(str))
    unique = np.unique(months)
    groups = {u: ix[months == u] for u in unique}
    draws = [one(np.concatenate([groups[u] for u in rng.choice(unique, len(unique))])) for _ in range(boot)]
    return est, [float(np.percentile(draws, 5)), float(np.percentile(draws, 95))], int(len(ix))


def _window_mask(T: pd.DatetimeIndex, start, end) -> np.ndarray:
    return np.asarray((T > pd.Timestamp(start)) & (T <= pd.Timestamp(end)))


def past_ratios(T, X, y, first_time, cut) -> dict[str, float]:
    ratios = {}
    h0 = pd.Timestamp(first_time) + pd.DateOffset(months=WINDOW_MONTHS)
    starts = [x for x in pd.date_range(pd.Timestamp(h0.year, 1, 1), cut, freq="MS") if x.month in (1, 7) and x >= h0]
    for s0 in starts:
        s1 = s0 + pd.DateOffset(months=6)
        if s1 > cut or s0 - pd.DateOffset(months=WINDOW_MONTHS) < pd.Timestamp(first_time):
            continue
        est_prev, _, _ = plateau(T, X, y, _window_mask(T, s0 - pd.DateOffset(months=WINDOW_MONTHS), s0))
        real, _, _ = plateau(T, X, y, _window_mask(T, s0, s1))
        if np.isfinite(est_prev) and np.isfinite(real) and est_prev < -0.02:
            ratios[str(s0.date())] = float(real / est_prev)
    return ratios


def fit_at(f: pd.DataFrame, R: pd.DataFrame, T, X, y, tau, boot: int = BOOT) -> dict | None:
    tau = pd.Timestamp(tau)
    cut = tau - GUARD
    lo = tau - pd.DateOffset(months=WINDOW_MONTHS)
    beta, ci, n_rows = plateau(T, X, y, _window_mask(T, lo, cut), boot=boot)
    if not np.isfinite(beta):
        return None
    ratios = past_ratios(T, X, y, f.index[0], cut)
    strong_mult = max(1.0, max(ratios.values())) if ratios else STRONG_DEFAULT
    weak = WEAK_MULT * beta if beta < 0 else math.nan
    strong = max(strong_mult * beta, STRONG_CAP) if beta < 0 else math.nan
    target_time = R.index + pd.Timedelta(HORIZON_H + 0.5, "h")
    usable = R.train_valid.to_numpy() & np.asarray(target_time <= cut)
    H = R[usable]
    return {
        "tau": tau.isoformat(),
        "beta_mgkg_per_c": round(float(beta), 4),
        "ci": [round(v, 4) for v in ci] if ci else None,
        "n_rows": n_rows,
        "weak_strong": ([round(float(weak), 3), round(float(strong), 3)] if np.isfinite(weak) else None),
        "strong_multiplier": round(float(strong_mult), 3),
        "past_ratios": {k: round(v, 3) for k, v in ratios.items()},
        "t6_range_c": [round(float(H.T6.quantile(.01)), 1), round(float(H.T6.quantile(.99)), 1)] if len(H) else None,
        "f9_range_tph": [round(float(H.F9.quantile(.01)), 1), round(float(H.F9.quantile(.99)), 1)] if len(H) else None,
        "n_history_rows": int(len(H)),
        "feed_floor_tph": round(float(f.attrs["feed_floor"]), 3),
        "feed_floor_until": f.attrs["feed_floor_until"],
        "window": [str(lo), str(cut)],
    }


def halves(index) -> np.ndarray:
    index = pd.DatetimeIndex(index)
    return np.asarray(index.year.astype(str)) + np.where(index.month <= 6, "H1", "H2")


def drift(T, X, y) -> list[dict]:
    hv = halves(T)
    out = []
    for h in sorted(np.unique(hv)):
        beta, _, _ = plateau(T, X, y, hv == h)
        if np.isfinite(beta):
            out.append({"tau": f"{h[:4]}-{'01' if h.endswith('H1') else '07'}-01", "beta": round(float(beta), 4)})
    return out


def tau_grid(index, train_end) -> list[pd.Timestamp]:
    index = pd.DatetimeIndex(index)
    first = pd.Timestamp(index[0]) + pd.DateOffset(months=WINDOW_MONTHS)
    last = pd.Timestamp(index[-1])
    taus = {x for x in pd.date_range(pd.Timestamp(first.year, 1, 1), last, freq="MS") if x.month in (1, 7) and x >= first}
    taus.add(pd.Timestamp(train_end))
    taus.add(last)
    return sorted(taus)


def estimate_response(signals: pd.DataFrame, online: pd.DataFrame, train_end, declared: dict,
                      model_fingerprint: str | None = None, boot: int = BOOT) -> dict:
    estimates = []
    parts_by_tau = {}
    for tau in tau_grid(signals.index, train_end):
        cut = pd.Timestamp(tau) - GUARD
        f = prepare(signals, online, feed_floor_until=cut)
        R = decision_rows(f, row_times(f))
        T, X, y = arx_design(f)
        estimate = fit_at(f, R, T, X, y, tau, boot=boot)
        if estimate is not None:
            estimates.append(estimate)
            parts_by_tau[pd.Timestamp(tau)] = (T, X, y)
    if not estimates:
        raise ValueError("Оценка отклика невозможна: ни в одном окне нет 5000 строк ARX")
    primary = next((e for e in estimates if pd.Timestamp(e["tau"]) == pd.Timestamp(train_end)), estimates[0])
    primary_parts = parts_by_tau[pd.Timestamp(primary["tau"])]
    method = (f"ARX({ARX_LAGS} lags, 10-min differences of {TEMPERATURE_TAG}, {FLOW_TAG}, PAK 30-min mean), beta = mean cumulative "
              f"PAK response at 3-8 h to a sustained +1 C step in T6; window = {WINDOW_MONTHS} months before tau minus 6 h guard; "
              f"rows = unit running >=12 h before and 6 h after (T6,T5>320 C, P13>3 MPa, F2>30000, "
              f"F9>q01 learned on hot rows no later than each tau minus 6 h, no NaN), PAK valid "
              f"(0.05-50 mg/kg, not frozen >=1 h); ci = month-block bootstrap "
              f"90% ({boot} draws, seed {SEED}); weak = 0.5*beta, strong = beta * max past realized/estimate ratio (cap {STRONG_CAP}); "
              f"drift = same ARX per half-year (realized) on the primary estimate's rows; estimated at training on the tau grid, the live decision takes the "
              f"latest tau <= decision time. Method of context/response-research/t6/response_model.py, unchanged.")
    keep = {k: v for k, v in declared.items()
            if k not in ("tau", "beta_mgkg_per_c", "ci", "n_rows", "drift", "model_fingerprint", "t6_range_c",
                         "f9_range_tph", "weak_strong", "method")}
    out = {"schema_version": SCHEMA_VERSION, "tag": TEMPERATURE_TAG, "flow_tag": FLOW_TAG, **keep,
           "window_months": WINDOW_MONTHS, "method": method, "flow_beta": declared.get("flow_beta"),
           "primary": "train_end", "train_end": str(pd.Timestamp(train_end)),
           **{k: primary[k] for k in ("tau", "beta_mgkg_per_c", "ci", "n_rows", "weak_strong", "t6_range_c",
                                         "f9_range_tph", "feed_floor_tph", "feed_floor_until")},
           "drift": drift(*primary_parts), "model_fingerprint": model_fingerprint,
           "selection_rule": "latest estimate with tau <= decision time; every window of an estimate ends at tau - 6 h",
           "estimates": estimates}
    return out


def response_at(response: dict | None, when) -> dict | None:
    if response is None:
        return None
    estimates = response.get("estimates")
    if not estimates:
        return response
    when = pd.Timestamp(when)
    chosen = None
    for estimate in estimates:
        if pd.Timestamp(estimate["tau"]) <= when and (estimate.get("ci") is not None):
            if chosen is None or pd.Timestamp(estimate["tau"]) > pd.Timestamp(chosen["tau"]):
                chosen = estimate
    if chosen is None:
        return None
    base = {k: v for k, v in response.items() if k != "estimates"}
    required = ("tau", "beta_mgkg_per_c", "ci", "n_rows", "weak_strong", "t6_range_c", "f9_range_tph")
    optional = ("feed_floor_tph", "feed_floor_until")
    selected = {k: chosen[k] for k in required}
    selected.update({k: chosen[k] for k in optional if k in chosen})
    return {**base, **selected}
