"""Reference implementation of the accepted temperature-response model (research copy, not src).

    S(t+3h | ΔT) = baseline_t + β_τ · ΔT
    baseline_t   = w_τ · PAK30m(t) + (1 − w_τ) · PAK24h(t)

τ is the fit time (artifact date). Every window used by fit() ends at τ; rows whose labels need future stability end at τ − 6 h.
Units: PAK in mg/kg (analyser ppm), T11 in °C, ΔT = sustained change of the reactor-inlet temperature setpoint, °C.
"""
from dataclasses import dataclass, field, asdict
import math

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

# ---- declared constants (policy / fixed on SELECT; not re-tuned) ----
HORIZON_H = 3.0
G = pd.Timedelta("6h")                   # guard: future-stability label may look 6 h ahead
BETA_WINDOW = pd.DateOffset(months=12)
W_WINDOW = (pd.DateOffset(months=18), pd.DateOffset(months=6))   # rows with target in (τ−18m, τ−6m]
R_WINDOW = pd.DateOffset(months=6)       # rows with target in (τ−6m, τ]
FS = 0.66                                # A30 -> sustained T at 3 h (F1 first stage, SELECT)
WEAK_MULT = 0.5                          # benefit is credited at most half of β (policy)
STRONG_DEFAULT = 2.5                     # used only if no past rolling-origin ratio exists
STRONG_CAP = -1.0                        # mg/kg per °C, expert Q&A 11.09 upper bound (prior, not data)
MAX_DT = 2.0
ZONE_A_MAX_DT = 1.0
MIN_ANALOGS_A = 5
SUPPORT_RADIUS_SD = 0.5
SUPPORT_COLS = ("T11", "T11_30d", "F26", "h2oil")
MAX_ARTIFACT_AGE = pd.DateOffset(months=6)
ARX_LAGS = 24                            # 4 h of 10-min lags
PLATEAU_STEPS = slice(17, 48)            # cumulative response at 3.0 … 8.0 h


# ------------------------------------------------------------------ preprocessing
def prepare(signals: pd.DataFrame, online: pd.DataFrame, frozen_rule: str = "past") -> pd.DataFrame:
    """10-min frame. All flags use only the past except `stable_label` (training row selection only)."""
    idx = signals.index
    f = pd.DataFrame(index=idx)
    f["T11"], f["T5"], f["F26"], f["F19"] = signals["ht.T11"], signals["ht.T5"], signals["ht.F26"], signals["ht.F19"]
    f["P13"], f["F2"] = signals["ht.P13"], signals["ht.F2"]
    f["h2oil"] = f.F2 / f.F26
    placeholder = (signals[["ht.T11", "ht.T6", "ht.T5", "ht.F26", "ht.F19", "ht.P13", "ht.F2"]] == 307).any(axis=1)
    running = ((f.F26 > 150) & (f.T11 > 320) & (f.T5 > 320) & (f.P13 > 3.0) & (f.F2 > 30000)
               & (f.F19 / f.F26).between(0.75, 0.9) & ~placeholder)
    f["running"] = running
    r = running.astype(float)
    f["run_past12h"] = r.rolling("12h").min().eq(1)                                   # live validity (past only)
    f["stable_label"] = f.run_past12h & r[::-1].rolling(37, min_periods=1).min()[::-1].eq(1)   # +6 h, training only
    p = online.set_index("time").value.sort_index()
    changed = p.diff().abs().gt(1e-6) | p.diff().isna()
    run = changed.cumsum()
    t = p.index.to_series()
    if frozen_rule == "past":      # plateau already ≥ 1 h long at this reading
        frozen = (t - t.groupby(run).transform("min")) >= pd.Timedelta("1h")
    else:                          # legacy: whole plateau ≥ 1 h (uses the plateau's future end)
        frozen = (t.groupby(run).transform("max") - t.groupby(run).transform("min")) >= pd.Timedelta("1h")
    grid = lambda s, how: s.resample("10min", label="right", closed="right").agg(how).reindex(idx)
    pak = grid(p, "mean")
    fr = grid(frozen.astype(float), "max").fillna(1.0).astype(bool)
    f["pak_raw"], f["pak_frozen"] = pak, fr
    f["pak"] = pak.where(~fr & pak.between(0.05, 50))
    f["T11_30d"] = f.T11.where(f.run_past12h).rolling("30d", min_periods=1000).mean()
    return f


def _wmean(s: pd.Series, t: pd.DatetimeIndex, start_min: int, end_min: int, min_valid: int = 1):
    width = (end_min - start_min) // 10
    return s.rolling(width, min_periods=min_valid).mean().reindex(t + pd.Timedelta(minutes=end_min)).to_numpy()


def rows(f: pd.DataFrame, times: pd.DatetimeIndex) -> pd.DataFrame:
    """Decision rows every 30 min: prediction inputs, historical action, label, support context."""
    d = pd.DataFrame(index=times)
    d["PAK30m"] = _wmean(f.pak, times, -30, 0, 1)
    d["PAK24h"] = _wmean(f.pak, times, -1440, 0, 72)
    d["PAK24h_cov"] = f.pak.notna().astype(float).rolling(144).mean().reindex(times).to_numpy()
    d["PAK1h"] = _wmean(f.pak, times, -60, 0, 1)
    d["T11"] = _wmean(f.T11, times, -30, 0, 1)
    d["F26"] = _wmean(f.F26, times, -30, 0, 1)
    d["h2oil"] = _wmean(f.h2oil, times, -30, 0, 1)
    d["T11_30d"] = f.T11_30d.reindex(times).to_numpy()
    d["run_past12h"] = f.run_past12h.reindex(times).fillna(False).to_numpy(bool)
    d["pak_frozen_now"] = f.pak_frozen.reindex(times).fillna(True).to_numpy(bool)
    d["A30"] = _wmean(f.T11, times, 0, 30, 1) - d.T11
    pre_T = d.T11 - _wmean(f.T11, times, -90, -60, 1)
    s_jump = d.PAK30m - _wmean(f.pak, times, -90, -30, 1)
    d["onset"] = (np.abs(pre_T) < .5) & (np.abs(s_jump) < .5) & (np.abs(d.PAK1h - d.PAK24h) < 1.0)
    d["y3"] = _wmean(f.pak, times, 180, 210, 2)
    ok = np.ones(len(times), bool)
    for off in (-420, -60, 0, 30, 60, 120, 180, 210):
        ok &= f.stable_label.reindex(times + pd.Timedelta(minutes=off)).fillna(False).to_numpy(bool)
    d["train_valid"] = ok & np.isfinite(d[["PAK30m", "PAK24h", "T11", "F26", "A30", "y3"]]).all(axis=1).to_numpy()
    return d


# ------------------------------------------------------------------ fit
@dataclass
class Artifact:
    tau: str
    w: float
    beta: float
    beta_ci90: list
    beta_weak: float
    beta_strong: float
    strong_mult: float
    r0: float
    r1: float
    T11_q01: float
    T11_q99: float
    F26_q01: float
    F26_q99: float
    support_mu: dict
    support_sd: dict
    analogs_z: np.ndarray = field(repr=False)
    analogs_A30: np.ndarray = field(repr=False)
    windows: dict = field(default_factory=dict)
    past_ratios: dict = field(default_factory=dict)

    def summary(self) -> dict:
        out = {k: v for k, v in asdict(self).items() if k not in ("analogs_z", "analogs_A30")}
        out["n_analogs_table"] = int(len(self.analogs_A30))
        return out


def arx_plateau(f: pd.DataFrame, start, end, boot: int = 0, seed: int = 0):
    """β: mean cumulative PAK response at 3–8 h to a permanent +1 °C T11 step; ARX on 10-min differences in (start, end]."""
    g = pd.DataFrame({"T11": f.T11, "F26": f.F26, "pak": f.pak.rolling("30min").mean()})
    D = g.diff()
    X = pd.concat({f"{c}_{j}": D[c].shift(j) for c in ("T11", "F26", "pak") for j in range(1, ARX_LAGS + 1)}, axis=1)
    m = (f.stable_label & f.pak.notna() & f.stable_label.shift(ARX_LAGS, fill_value=False) & X.notna().all(axis=1)
         & D.pak.notna() & (f.index > start) & (f.index <= end)).to_numpy()
    Xm, ym, T = X.to_numpy()[m], D.pak.to_numpy()[m], f.index[m]

    def one(ix):
        c = LinearRegression().fit(Xm[ix], ym[ix]).coef_
        b, a = c[:ARX_LAGS], c[2 * ARX_LAGS:3 * ARX_LAGS]
        n = 54
        u = np.zeros(n + ARX_LAGS); u[ARX_LAGS] = 1.0
        ys = np.zeros(n + ARX_LAGS)
        for k in range(ARX_LAGS, n + ARX_LAGS):
            ys[k] = b @ u[k - ARX_LAGS:k][::-1] + a @ ys[k - ARX_LAGS:k][::-1]
        return float(np.cumsum(ys[ARX_LAGS:])[PLATEAU_STEPS].mean())
    if m.sum() < 5000:
        return (np.nan, [np.nan, np.nan]) if boot else np.nan
    allix = np.arange(len(ym))
    est = one(allix)
    if not boot:
        return est
    rng = np.random.default_rng(seed)
    mon = np.asarray(T.to_period("M").astype(str)); um = np.unique(mon); gi = {u: np.flatnonzero(mon == u) for u in um}
    bs = [one(np.concatenate([gi[u] for u in rng.choice(um, len(um))])) for _ in range(boot)]
    return est, [float(np.percentile(bs, 5)), float(np.percentile(bs, 95))]


def fit(f: pd.DataFrame, R: pd.DataFrame, tau, boot: int = 40) -> Artifact:
    """f = prepare(...) frame, R = rows(f, 30-min times). Uses only data with (label) time <= tau − G."""
    tau = pd.Timestamp(tau)
    cut = tau - G
    target_time = R.index + pd.Timedelta(hours=HORIZON_H + 0.5)
    usable = R.train_valid.to_numpy() & np.asarray(target_time <= cut)
    # 1. baseline weight on rows with target in (τ−18m, τ−6m]
    w_lo, w_hi = tau - W_WINDOW[0], tau - W_WINDOW[1]
    mw = usable & np.asarray((target_time > w_lo) & (target_time <= w_hi))
    Rw = R[mw]
    grid = np.round(np.linspace(0, 1, 21), 2)
    w = float(grid[np.argmin([np.mean(np.abs(Rw.y3 - (x * Rw.PAK30m + (1 - x) * Rw.PAK24h))) for x in grid])])
    # 2. β on 10-min data in (τ−12m, τ−6h]
    if boot:
        beta, ci = arx_plateau(f, tau - BETA_WINDOW, cut, boot=boot)
    else:
        beta, ci = arx_plateau(f, tau - BETA_WINDOW, cut), [np.nan, np.nan]
    # 3. strong multiplier: max past rolling-origin ratio realized/estimate over half-years ending before τ−6h
    ratios = {}
    h0 = pd.Timestamp(f.index[0]) + pd.DateOffset(months=12)
    starts = [x for x in pd.date_range(pd.Timestamp(h0.year, 1, 1), cut, freq="MS") if x.month in (1, 7) and x >= h0]
    for s0 in starts:
        s1 = s0 + pd.DateOffset(months=6)
        if s1 > cut or s0 - pd.DateOffset(months=12) < f.index[0]:
            continue
        est_prev = arx_plateau(f, s0 - pd.DateOffset(months=12), s0)
        real = arx_plateau(f, s0, s1)
        if np.isfinite(est_prev) and np.isfinite(real) and est_prev < -0.02:
            ratios[str(s0.date())] = float(real / est_prev)
    strong_mult = max(1.0, max(ratios.values())) if ratios else STRONG_DEFAULT
    beta_strong = max(strong_mult * beta, STRONG_CAP) if beta < 0 else np.nan
    beta_weak = WEAK_MULT * beta if beta < 0 else np.nan
    # 4. radii on rows with target in (τ−6m, τ−6h], residual of the full model on the delivered move FS·A30
    mr = usable & np.asarray(target_time > tau - R_WINDOW)
    Rr = R[mr]
    mid = w * Rr.PAK30m + (1 - w) * Rr.PAK24h + beta * FS * Rr.A30
    res = np.abs(Rr.y3 - mid)
    r0 = float(np.quantile(res[np.abs(Rr.A30) < 1], .9))
    r1 = float(np.quantile(res[np.abs(Rr.A30) >= 1], .9))
    # 5. support context from all valid history before τ
    H = R[usable]
    mu = {c: float(H[c].mean()) for c in SUPPORT_COLS}
    sd = {c: float(H[c].std()) for c in SUPPORT_COLS}
    On = H[H.onset & np.isfinite(H[list(SUPPORT_COLS)]).all(axis=1)]
    Z = np.column_stack([(On[c] - mu[c]) / sd[c] for c in SUPPORT_COLS])
    return Artifact(
        tau=str(tau), w=w, beta=float(beta), beta_ci90=ci, beta_weak=float(beta_weak), beta_strong=float(beta_strong),
        strong_mult=float(strong_mult), r0=r0, r1=r1,
        T11_q01=float(H.T11.quantile(.01)), T11_q99=float(H.T11.quantile(.99)),
        F26_q01=float(H.F26.quantile(.01)), F26_q99=float(H.F26.quantile(.99)),
        support_mu=mu, support_sd=sd, analogs_z=Z, analogs_A30=On.A30.to_numpy(),
        windows={"w_rows_target": [str(w_lo), str(w_hi)], "beta_10min": [str(tau - BETA_WINDOW), str(cut)],
                 "radius_rows_target": [str(tau - R_WINDOW), str(cut)], "n_w_rows": int(mw.sum()),
                 "n_radius_rows": int(mr.sum()), "n_radius_action_rows": int((np.abs(Rr.A30) >= 1).sum())},
        past_ratios=ratios)


# ------------------------------------------------------------------ predict
def live_state(f: pd.DataFrame, t) -> dict:
    """Everything predict() needs at time t, from data up to t only."""
    t = pd.Timestamp(t)
    r = rows(f, pd.DatetimeIndex([t])).iloc[0]
    keys = ["PAK30m", "PAK24h", "PAK24h_cov", "T11", "T11_30d", "F26", "h2oil", "run_past12h", "pak_frozen_now"]
    return {"time": t, **{k: (r[k].item() if hasattr(r[k], "item") else r[k]) for k in keys}}


def support_count(art: Artifact, state: dict, dT: float) -> int:
    z = np.array([(state[c] - art.support_mu[c]) / art.support_sd[c] for c in SUPPORT_COLS])
    near = np.sqrt(((art.analogs_z - z) ** 2).sum(1)) <= SUPPORT_RADIUS_SD
    same = (np.sign(art.analogs_A30) == np.sign(dT)) & (np.abs(art.analogs_A30 - dT) <= 0.5)
    return int((near & same).sum())


def predict(art: Artifact, state: dict, dT: float) -> dict:
    reasons = []
    now = pd.Timestamp(state["time"])
    if now - pd.Timestamp(art.tau) > pd.Timedelta(days=183) or now < pd.Timestamp(art.tau):
        reasons.append("artifact older than 6 months or from the future")
    if not state["run_past12h"]:
        reasons.append("no 12 h of continuous running")
    if state["pak_frozen_now"] or not np.isfinite(state["PAK30m"]):
        reasons.append("PAK frozen or missing in last 30 min")
    if not np.isfinite(state["PAK24h"]) or state["PAK24h_cov"] < 0.5:
        reasons.append("PAK 24 h coverage < 50%")
    if dT != 0:
        if not (np.isfinite(art.beta) and art.beta < 0):
            reasons.append("β_τ not negative: response not usable")
        if abs(dT) > MAX_DT:
            reasons.append(f"|ΔT| > {MAX_DT} °C")
        if not (art.T11_q01 <= state["T11"] <= art.T11_q99) or not (art.T11_q01 <= state["T11"] + dT <= art.T11_q99):
            reasons.append("T11 or T11+ΔT outside history q01–q99")
        if not (art.F26_q01 <= state["F26"] <= art.F26_q99):
            reasons.append("F26 outside history q01–q99")
        if not all(np.isfinite(state[c]) for c in SUPPORT_COLS):
            reasons.append("support context missing")
    if reasons:
        return {"zone": "C_FORBIDDEN", "reasons": reasons, "delta_T": dT}
    base = art.w * state["PAK30m"] + (1 - art.w) * state["PAK24h"]
    if dT == 0:
        return {"zone": "HOLD", "delta_T": 0.0, "baseline": base, "sulfur_mid": base,
                "lower": max(0.0, base - art.r0), "upper": base + art.r0, "effect_mid": 0.0, "effect_weak": 0.0, "effect_strong": 0.0,
                "support_analogs": None, "beta_tau": art.beta, "artifact_tau": art.tau}
    e_mid, e_weak, e_strong = art.beta * dT, art.beta_weak * dT, art.beta_strong * dT
    lo_e, hi_e = min(e_weak, e_strong), max(e_weak, e_strong)
    n = support_count(art, state, dT)
    zone = "A_SUPPORTED" if (abs(dT) <= ZONE_A_MAX_DT and n >= MIN_ANALOGS_A) else "B_EXTRAPOLATION"
    return {"zone": zone, "delta_T": dT, "baseline": base, "sulfur_mid": base + e_mid,
            "lower": max(0.0, base + lo_e - art.r1), "upper": base + hi_e + art.r1,
            "effect_mid": e_mid, "effect_weak": e_weak, "effect_strong": e_strong, "support_analogs": n,
            "beta_tau": art.beta, "artifact_tau": art.tau}
