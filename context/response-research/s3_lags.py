"""Stage 4: lags, transients, feedback direction. Output out/s3_lags.json + figures.

(a) PAK vs LIMS: which PAK offset best matches lab sample (transport/sampling offset).
(b) Cross-correlation of hourly differences dT_in(t) vs dPAK(t+k), k=-12..12 (negative k = PAK leads T: feedback).
(c) Event study around clean T/feed step events: PAK trajectory relative to pre-event level, up vs down.
(d) ARX in differences (10-min): dPAK_t ~ sum_j b_j dT_{t-j} + c_j dFeed_{t-j} + a_j dPAK_{t-j}; cumulative gain.
(e) Reverse ARX: dT_t ~ past dPAK: does temperature respond to sulfur (APC)?
"""
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.linear_model import LinearRegression

from common import *

f = pd.read_pickle(OUT / "frame.pkl")
s, lab, on, ex = load()
res = {}

# (a) PAK vs LIMS offset
p = f.pak
L = lab.set_index("time").value
rows = []
for off in range(-240, 241, 30):
    v = p.rolling("30min").mean().reindex(L.index + pd.Timedelta(minutes=off), method="nearest",
                                          tolerance=pd.Timedelta("10min"))
    v.index = L.index
    m = v.notna()
    rows.append({"offset_min": off, "n": int(m.sum()), "corr": float(np.corrcoef(v[m], L[m])[0, 1]),
                 "mae": float((v[m] - L[m]).abs().mean()), "bias": float((v[m] - L[m]).mean())})
res["pak_vs_lims_offset"] = rows

# Hourly series
h = pd.read_pickle(OUT / "hourly.pkl")
ok = h.stable
dT = (h.T_in - h.T_in.shift(1)).where(ok & ok.shift(1, fill_value=False))
dF = (h.feed - h.feed.shift(1)).where(ok & ok.shift(1, fill_value=False))
dS = (h.pak - h.pak.shift(1)).where(ok & ok.shift(1, fill_value=False))
xc = {}
for name, d in [("T_in", dT), ("feed", dF)]:
    xc[name] = {}
    for k in range(-12, 13):
        pair = pd.concat([d, dS.shift(-k)], axis=1).dropna()
        xc[name][k] = float(pair.corr().iloc[0, 1])
res["xcorr_hourly_d_vs_dPAK_lead_k"] = xc

# Level (not differenced) within-day correlation: detrended by 48h rolling mean
def detr(x, w="48h"):
    return x - x.rolling(w, center=True, min_periods=24).mean()
xl = {}
for name in ["T_in", "feed"]:
    a, b = detr(h[name].where(ok)), detr(h.pak.where(ok))
    xl[name] = {k: float(pd.concat([a, b.shift(-k)], axis=1).dropna().corr().iloc[0, 1]) for k in range(-12, 13)}
res["xcorr_detrended_levels"] = xl

# (c) Event study (reuse step definition from s2)
def events(x, thr, flat, hold):
    d = x.shift(-1) - x
    pre = x.rolling(4).max() - x.rolling(4).min()
    post = (x.shift(-1).rolling(3).mean().shift(-2) - x.shift(-1)).abs()
    st = h.stable & h.stable.shift(-12, fill_value=False) & h.stable.shift(6, fill_value=False)
    e = (d.abs() >= thr) & (pre <= flat) & (post <= hold) & st
    return e[e].index, d

K = range(-6, 13)
study = {}
fig, axes = plt.subplots(2, 2, figsize=(14, 9))
for col, (var, thr, flat, hold) in enumerate([("T_in", 1.5, 1.0, 1.0), ("feed", 8, 6, 6)]):
    idx, d = events(h[var], thr, flat, hold)
    study[var] = {}
    for sign, lab_ in [(1, "up"), (-1, "down")]:
        ii = [t for t in idx if np.sign(d[t]) == sign]
        mat_s, mat_x, mat_o = [], [], []
        other = "feed" if var == "T_in" else "T_in"
        for t in ii:
            base_s = h.pak.loc[t - pd.Timedelta("2h"):t].mean()
            base_x = h[var].loc[t]
            base_o = h[other].loc[t]
            ts = [t + pd.Timedelta(hours=k) for k in K]
            mat_s.append(h.pak.reindex(ts).to_numpy() - base_s)
            mat_x.append(h[var].reindex(ts).to_numpy() - base_x)
            mat_o.append(h[other].reindex(ts).to_numpy() - base_o)
        S, X, O = np.array(mat_s), np.array(mat_x), np.array(mat_o)
        n = len(ii)
        study[var][lab_] = {
            "n": n, "k": list(K),
            "pak_mean": np.nanmean(S, 0).round(3).tolist(),
            "pak_se": (np.nanstd(S, 0) / np.sqrt(max(n, 1))).round(3).tolist(),
            "var_mean": np.nanmean(X, 0).round(3).tolist(),
            "other_mean": np.nanmean(O, 0).round(3).tolist(),
        }
        ax = axes[0, col]
        ax.errorbar(list(K), np.nanmean(S, 0), yerr=1.96 * np.nanstd(S, 0) / np.sqrt(max(n, 1)), label=f"PAK, {lab_} n={n}", capsize=2)
        axes[1, col].plot(list(K), np.nanmean(X, 0), label=f"{var} {lab_}")
        axes[1, col].plot(list(K), np.nanmean(O, 0), "--", label=f"{other} {lab_}")
    axes[0, col].axvline(0, color="k", lw=.5); axes[0, col].axhline(0, color="k", lw=.5)
    axes[0, col].set_title(f"PAK change around {var} steps (step between hour 0 and 1)")
    axes[0, col].legend(); axes[1, col].legend(); axes[1, col].axvline(0, color="k", lw=.5)
plt.tight_layout(); plt.savefig(OUT / "fig" / "event_study.png", dpi=70)
res["event_study"] = study

# (d)/(e) ARX in differences on 10-min grid, stable, valid PAK
g = f[["T_in", "feed", "pak", "stable", "gas22"]].copy()
g["pak"] = g.pak.rolling("30min").mean()  # smooth analyser noise, causal
D = g[["T_in", "feed", "pak", "gas22"]].diff()
valid = g.stable & g.pak.notna()
LAGS = 24  # 4 h of 10-min lags
def lagmat(cols, lags):
    return pd.concat({f"{c}_{j}": D[c].shift(j) for c in cols for j in range(1, lags + 1)}, axis=1)
Xf = lagmat(["T_in", "feed", "pak"], LAGS)
y = D.pak
m = valid & Xf.notna().all(axis=1) & y.notna() & valid.shift(LAGS, fill_value=False)
# Use only 2023-2025 for estimation
m_tr = m & (g.index < "2026-01-01")
reg = LinearRegression().fit(Xf[m_tr], y[m_tr])
coef = pd.Series(reg.coef_, Xf.columns)

def impulse(coef, src, steps=36):
    """Response of PAK level to a permanent +1 step in src, via simulated ARX recursion (differences)."""
    b = np.array([coef[f"{src}_{j}"] for j in range(1, LAGS + 1)])
    a = np.array([coef[f"pak_{j}"] for j in range(1, LAGS + 1)])
    u = np.zeros(steps + LAGS); u[LAGS] = 1.0   # one-time difference = permanent level step
    ys = np.zeros(steps + LAGS)
    for t in range(LAGS, steps + LAGS):
        ys[t] = sum(b[j - 1] * u[t - j] for j in range(1, LAGS + 1)) + sum(a[j - 1] * ys[t - j] for j in range(1, LAGS + 1))
    return np.cumsum(ys[LAGS:]).round(4).tolist()
res["arx_pak_on_T_feed"] = {"n": int(m_tr.sum()), "r2": float(reg.score(Xf[m_tr], y[m_tr])),
                            "step_response_T_+1C_10min": impulse(coef, "T_in"),
                            "step_response_feed_+1m3h_10min": impulse(coef, "feed")}
# bootstrap by month blocks for step response of T at 3 h
months = g.index[m_tr].to_period("M")
uniq = months.unique()
rng = np.random.default_rng(0)
boots = []
Xtr, ytr = Xf[m_tr].to_numpy(), y[m_tr].to_numpy()
mon = np.asarray(months)
groups = {u: np.flatnonzero(mon == u) for u in uniq}
for b in range(60):
    pick = rng.choice(uniq, len(uniq))
    ii = np.concatenate([groups[u] for u in pick])
    rb = LinearRegression().fit(Xtr[ii], ytr[ii])
    cb = pd.Series(rb.coef_, Xf.columns)
    boots.append([impulse(cb, "T_in")[k] for k in (6, 12, 18, 24, 35)] + [impulse(cb, "feed")[k] for k in (6, 12, 18, 24, 35)])
B = np.array(boots)
res["arx_bootstrap_month_blocks"] = {
    "T_at_h": {h_: [float(np.percentile(B[:, i], 5)), float(np.median(B[:, i])), float(np.percentile(B[:, i], 95))]
               for i, h_ in enumerate(["1h", "2h", "3h", "4h", "6h"])},
    "feed_at_h": {h_: [float(np.percentile(B[:, 5 + i], 5)), float(np.median(B[:, 5 + i])), float(np.percentile(B[:, 5 + i], 95))]
                  for i, h_ in enumerate(["1h", "2h", "3h", "4h", "6h"])},
}
# Reverse: dT_t on past dPAK and past dT, dfeed
Xr = lagmat(["pak", "T_in", "feed"], LAGS)
yr = D.T_in
mr = valid & Xr.notna().all(axis=1) & yr.notna() & (g.index < "2026-01-01") & valid.shift(LAGS, fill_value=False)
rr = LinearRegression().fit(Xr[mr], yr[mr])
cr = pd.Series(rr.coef_, Xr.columns)
full = rr.score(Xr[mr], yr[mr])
Xr2 = Xr[[c for c in Xr if not c.startswith("pak_")]]
r2 = LinearRegression().fit(Xr2[mr], yr[mr]).score(Xr2[mr], yr[mr])
res["reverse_T_on_past_pak"] = {"sum_pak_coef_4h": float(sum(cr[f"pak_{j}"] for j in range(1, LAGS + 1))),
                                "r2_with_pak": full, "r2_without_pak": r2}
# Also: T change over next 3h vs PAK deviation now (APC behaviour)
dev = (h.pak - h.pak.rolling("24h").mean()).where(ok)
fut = (h.T_in.shift(-3) - h.T_in).where(ok & ok.shift(-3, fill_value=False))
pair = pd.concat([dev, fut], axis=1).dropna()
bins = pd.cut(pair.iloc[:, 0], [-10, -2, -1, -.5, .5, 1, 2, 10])
res["future_dT3h_by_pak_deviation"] = pair.groupby(bins, observed=True).iloc[:, 1].agg(["count", "mean"]).round(3).reset_index().astype(str).values.tolist() if False else \
    pair.iloc[:, 1].groupby(bins, observed=True).agg(["count", "mean"]).round(3).to_dict("index")
res["future_dT3h_by_pak_deviation"] = {str(k): v for k, v in res["future_dT3h_by_pak_deviation"].items()}

(OUT / "s3_lags.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
print(pd.DataFrame(res["pak_vs_lims_offset"]).round(3).to_string())
print("xcorr diff", {k: {kk: round(vv, 3) for kk, vv in v.items()} for k, v in xc.items()})
print("xcorr detr", {k: {kk: round(vv, 3) for kk, vv in v.items()} for k, v in xl.items()})
for var in study:
    for d_ in study[var]:
        e = study[var][d_]
        print(var, d_, e["n"], "pak", e["pak_mean"], "\n   var", e["var_mean"], "\n   other", e["other_mean"])
print(json.dumps({k: res[k] for k in ["arx_pak_on_T_feed", "arx_bootstrap_month_blocks", "reverse_T_on_past_pak",
                                      "future_dT3h_by_pak_deviation"]}, indent=1))
