"""Stage 5: how much of the action effect is identifiable from observational data.

1. Action predictability: R² of aT and aF from state (CatBoost, time-block cross-fitting). High R² = action mostly a
   reaction to state (little independent variation).
2. Double ML (partialling out, time-block cross-fitting): y~ = y − E[y|state], a~ = a − E[a|state];
   OLS of y~ on (aT~, aF~) per year and pooled, week-block bootstrap 90% CI.
3. Unprovoked subset: no PAK excursion before the move (|s_trend|<0.3 and |s_1h − s_6h|<0.5).
4. LIMS check: lab sulfur at sample time vs actions right after decision time (sample − 2 h), independent target.
Output out/s6_identification.json
"""
import json
import warnings

warnings.filterwarnings("ignore")
from catboost import CatBoostRegressor

from common import *

d = pd.read_pickle(OUT / "ds.pkl")
rng = np.random.default_rng(0)
res = {}


def cb():
    return CatBoostRegressor(iterations=400, depth=5, learning_rate=0.05, random_seed=0, thread_count=8,
                             verbose=False, allow_writing_files=False)


def crossfit(X, y, nblocks=12):
    """Out-of-fold predictions with contiguous time blocks, 1-day embargo around the held-out block."""
    n = len(X)
    pred = np.full(n, np.nan)
    idx = np.arange(n)
    t = X.index
    for b in np.array_split(idx, nblocks):
        lo, hi = t[b[0]] - pd.Timedelta("1d"), t[b[-1]] + pd.Timedelta("1d")
        tr = (t < lo) | (t > hi)
        m = cb().fit(X[tr], y[tr])
        pred[b] = m.predict(X.iloc[b])
    return pred


def ols2(ya, a1, a2):
    A = np.column_stack([a1, a2, np.ones_like(a1)])
    return np.linalg.lstsq(A, ya, rcond=None)[0][:2]


def boot(ya, a1, a2, weeks, draws=400):
    uw = np.unique(weeks)
    g = {w: np.flatnonzero(weeks == w) for w in uw}
    est = ols2(ya, a1, a2)
    bs = []
    for _ in range(draws):
        ii = np.concatenate([g[w] for w in rng.choice(uw, len(uw))])
        bs.append(ols2(ya[ii], a1[ii], a2[ii]))
    bs = np.array(bs)
    return {"theta_T_ppm_per_C": [float(est[0]), float(np.percentile(bs[:, 0], 5)), float(np.percentile(bs[:, 0], 95))],
            "theta_feed_ppm_per_1pct": [float(est[1] / 100), float(np.percentile(bs[:, 1], 5) / 100),
                                        float(np.percentile(bs[:, 1], 95) / 100)],
            "n": int(len(ya))}


D0 = d[d.valid].copy()
X = D0[STATE]
aT_hat = crossfit(X, D0.a_T_in.to_numpy())
aF_hat = crossfit(X, D0.a_feed_rel.to_numpy())
aTr, aFr = D0.a_T_in.to_numpy() - aT_hat, D0.a_feed_rel.to_numpy() - aF_hat
res["action_predictability_R2"] = {
    "aT": float(1 - np.var(aTr) / np.var(D0.a_T_in)), "aF": float(1 - np.var(aFr) / np.var(D0.a_feed_rel))}
res["residual_action_std"] = {"aT": float(np.std(aTr)), "aF": float(np.std(aFr)),
                              "aT_raw": float(D0.a_T_in.std()), "aF_raw": float(D0.a_feed_rel.std())}
print(res)

weeks_all = np.asarray(D0.index.to_period("W").astype(str))
years = D0.index.year
unprov = ((D0.s_trend.abs() < .3) & ((D0.s_1h - D0.s_6h).abs() < .5)).to_numpy()
res["unprovoked_share"] = float(unprov.mean())
res["dml"] = {}
for h in (1, 2, 3):
    y = D0[f"y{h}"].to_numpy() - D0.s_1h.to_numpy()
    ok = np.isfinite(y) & (D0[f"y{h}_cov"] >= .5).to_numpy()
    yhat = np.full(len(y), np.nan)
    yhat[ok] = crossfit(X[ok], y[ok])
    yr = y - yhat
    out = {}
    for label, m in [("pooled", ok), ("unprovoked", ok & unprov)]:
        out[label] = boot(yr[m], aTr[m], aFr[m], weeks_all[m])
    for yy in [2023, 2024, 2025, 2026]:
        m = ok & (years == yy)
        out[str(yy)] = boot(yr[m], aTr[m], aFr[m], weeks_all[m], draws=200)
        m2 = m & unprov
        out[f"{yy}_unprovoked"] = boot(yr[m2], aTr[m2], aFr[m2], weeks_all[m2], draws=200)
    res["dml"][h] = out
    print(h, json.dumps({k: (v["theta_T_ppm_per_C"], v["theta_feed_ppm_per_1pct"], v["n"]) for k, v in out.items()}))

# LIMS check
s, lab, on, ex = load()
L = lab.copy()
L["t"] = (L.time - pd.Timedelta("2h")).dt.floor("h")
J = L.merge(D0[["s_1h", "a_T_in", "a_feed_rel", "s_trend", "s_6h"]].assign(aTr=aTr, aFr=aFr),
            left_on="t", right_index=True, how="inner")
yl = (J.value - J.s_1h).to_numpy()
wk = np.asarray(J.t.dt.to_period("W").astype(str))
res["lims_check"] = {"raw_actions": boot(yl, J.a_T_in.to_numpy(), J.a_feed_rel.to_numpy(), wk),
                     "residual_actions": boot(yl - np.mean(yl), J.aTr.to_numpy(), J.aFr.to_numpy(), wk),
                     "n_|aT|>=1": int((J.a_T_in.abs() >= 1).sum())}
print("lims", res["lims_check"])
(OUT / "s6_identification.json").write_text(json.dumps(res, indent=1, default=str))
