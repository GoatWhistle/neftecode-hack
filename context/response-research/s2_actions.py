"""Stage 2: which HT variables move, how, how often, how independently. Output out/s2_*.json, figures.

Action definitions tested (hourly means on stable running):
  dX_1h(t) = mean X over (t, t+1h] - mean X over (t-1h, t]    (move made in the next hour)
Step event for X: |dX over 1 h| >= thr, previous 3 h flat (range small), and new level held 3 h after.
"""
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from common import *

f = pd.read_pickle(OUT / "frame.pkl")
VARS = ["T_in", "T_out", "feed", "h2oil", "gas2", "gas22", "gas25", "P", "quench"]
res = {}

# Multi-scale variability (stable only)
scales = {"10min": 1, "1h": 6, "3h": 18, "12h": 72, "1d": 144, "7d": 1008}
var = {}
for v in VARS + ["pak"]:
    x = f[v].where(f.stable)
    var[v] = {k: float(x.diff(n).abs().median()) for k, n in scales.items()}
    var[v]["q95_1h"] = float(x.diff(6).abs().quantile(.95))
res["median_abs_change_by_scale"] = var

# Yearly level (catalyst ageing / drift)
yearly = f.loc[f.stable, ["T_in", "T_out", "feed", "h2oil", "gas22", "pak"]].groupby(f.index[f.stable].to_period("Q")).mean()
res["quarterly_mean"] = {str(k): v for k, v in yearly.round(2).to_dict("index").items()}

# Hourly frame
h = f[VARS + ["pak", "stable"]].resample("1h", label="right", closed="right").mean()
h["stable"] = h.stable == 1
H = pd.DataFrame(index=h.index)
for v in VARS:
    H["d_" + v] = h[v].shift(-1) - h[v]           # change over the next hour
H = H[h.stable & h.stable.shift(-1, fill_value=False)]
corr = H.corr().round(2)
res["hourly_change_corr"] = corr.to_dict()

# Rolling flatness helpers on hourly means
def events(x: pd.Series, thr: float, flat: float, hold: float):
    """Step: |x[t+1]-x[t]| >= thr, range over [t-3,t] <= flat, |mean(x[t+1..t+3]) - x[t+1]| <= hold."""
    d = x.shift(-1) - x
    pre = x.rolling(4).max() - x.rolling(4).min()
    post = (x.shift(-1).rolling(3).mean().shift(-2) - x.shift(-1)).abs()
    return (d.abs() >= thr) & (pre <= flat) & (post <= hold), d

thresholds = {"T_in": [(1.0, 1.0, .7), (2.0, 1.0, 1.0), (3.0, 1.5, 1.5)],
              "feed": [(5, 5, 4), (10, 6, 6), (15, 8, 8)],
              "h2oil": [(15, 15, 10), (30, 20, 15)],
              "gas22": [(500, 300, 300), (1000, 500, 500)]}
ev = {}
stable_h = h.stable & h.stable.shift(-4, fill_value=False) & h.stable.shift(4, fill_value=False)
for v, ths in thresholds.items():
    ev[v] = []
    for thr, flat, hold in ths:
        e, d = events(h[v], thr, flat, hold)
        e = e & stable_h
        idx = e[e].index
        others = {}
        for o in ["T_in", "feed", "h2oil", "gas22", "pak"]:
            if o == v:
                continue
            od = (h[o].shift(-1) - h[o]).reindex(idx).abs()
            others[o] = {"median_abs_same_hour": float(od.median()) if len(od) else None}
        ev[v].append({"thr": thr, "flat": flat, "hold": hold, "n": int(len(idx)),
                      "n_up": int((d[idx] > 0).sum()), "n_down": int((d[idx] < 0).sum()),
                      "by_year": pd.Series(1, idx).groupby(idx.year).sum().to_dict(),
                      "median_abs_step": float(d[idx].abs().median()) if len(idx) else None,
                      "co_moves": others})
res["step_events"] = ev

# Distribution of hourly T change and how often |dT|>=x
dT = H["d_T_in"]
res["hourly_dT_share_ge"] = {str(x): float((dT.abs() >= x).mean()) for x in [0.5, 1, 2, 3, 4, 5]}
dF = H["d_feed"]
res["hourly_dfeed_share_ge"] = {str(x): float((dF.abs() >= x).mean()) for x in [2, 5, 10, 15, 20]}
# 3-hour sustained change
d3 = (h.T_in.shift(-3) - h.T_in)[h.stable]
res["3h_dT_share_ge"] = {str(x): float((d3.abs() >= x).mean()) for x in [1, 2, 3, 4, 5]}
rel = ((h.feed.shift(-3) - h.feed) / h.feed)[h.stable]
res["3h_dfeed_rel_share_ge"] = {str(x): float((rel.abs() >= x).mean()) for x in [.02, .05, .1]}

# Joint: when |dT_3h|>=2, how often |dfeed_3h|>=5%?
j = pd.DataFrame({"dT": d3, "df": rel}).dropna()
res["joint_3h"] = {
    "n": len(j),
    "P(|df|>=5% | |dT|>=2)": float((j.df.abs() >= .05)[j.dT.abs() >= 2].mean()),
    "P(|df|>=5%)": float((j.df.abs() >= .05).mean()),
    "P(|dT|>=2 | |df|>=5%)": float((j.dT.abs() >= 2)[j.df.abs() >= .05].mean()),
    "P(|dT|>=2)": float((j.dT.abs() >= 2).mean()),
    "corr_dT_df": float(j.corr().iloc[0, 1]),
}

(OUT / "s2_actions.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
h.to_pickle(OUT / "hourly.pkl")
print(json.dumps({k: res[k] for k in ["median_abs_change_by_scale", "hourly_dT_share_ge", "hourly_dfeed_share_ge",
                                      "3h_dT_share_ge", "3h_dfeed_rel_share_ge", "joint_3h"]}, indent=1))
print(pd.DataFrame(res["quarterly_mean"]).T)
print(corr)
for v, lst in ev.items():
    for e in lst:
        print(v, {k: e[k] for k in ["thr", "n", "n_up", "n_down", "by_year", "median_abs_step"]}, e["co_moves"])
