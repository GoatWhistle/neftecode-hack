"""F8: numbers for the final artifact + post-hoc coverage check of the chosen coefficient rule.

Rule (chosen after F6/F7, flagged post-hoc): β = ARX plateau (3–8 h) on trailing 12 months; range [2.5·β (strong), 0.5·β (weak)]
(multipliers cover rolling-origin ratios 0.9–2.5). Baseline: blend weight w and conformal radii as in F4.
(1) Coverage on EVAL1/EVAL2 with β from trailing 12 months before each half (no EVAL data inside its own β).
(2) Current artifact numbers from the last 12 months of data.
Output out/f8_artifact.json
"""
import pickle
from sklearn.linear_model import LinearRegression

from fcommon import *

M_ = pickle.load((OUT / "f4_models.pkl").open("rb"))
FS = M_["FS"]
f = pd.read_pickle(OUT1 / "frame.pkl")
g10 = f[["T_in", "feed", "pak", "stable"]].copy(); g10["pak"] = g10.pak.rolling("30min").mean()
D10 = g10[["T_in", "feed", "pak"]].diff(); L = 24
Xl = pd.concat({f"{c}_{j}": D10[c].shift(j) for c in ["T_in", "feed", "pak"] for j in range(1, L + 1)}, axis=1)
m = (g10.stable & g10.pak.notna() & g10.stable.shift(L, fill_value=False) & Xl.notna().all(axis=1) & D10.pak.notna()).to_numpy()
T = g10.index[m]; Xm = Xl.to_numpy()[m]; ym = D10.pak.to_numpy()[m]


def plateau(mask, boot=0):
    def one(ix):
        c = LinearRegression().fit(Xm[ix], ym[ix]).coef_
        b, a = c[:L], c[2 * L:3 * L]; u = np.zeros(54 + L); u[L] = 1; ys = np.zeros(54 + L)
        for t in range(L, 54 + L): ys[t] = b @ u[t - L:t][::-1] + a @ ys[t - L:t][::-1]
        return float(np.cumsum(ys[L:])[17:48].mean())
    ix = np.flatnonzero(mask); est = one(ix)
    if not boot: return est
    mon = np.asarray(T[ix].to_period("M").astype(str)); um = np.unique(mon); gi = {u: ix[mon == u] for u in um}
    bs = [one(np.concatenate([gi[u] for u in rng.choice(um, len(um))])) for _ in range(boot)]
    return [est, float(np.percentile(bs, 5)), float(np.percentile(bs, 95))]

d = pd.read_pickle(OUT / "ds_final.pkl")
D = d[d.valid & d.y3.notna() & (d.cov3 >= .6)].copy()
P = periods(D.index + pd.Timedelta(hours=3.5), D.index)
w = M_["blend_w"]; r, ra = M_["radius"]["P2_additive"], M_["radius_action"]["P2_additive"]
s24 = np.where(np.isfinite(D.s_24h), D.s_24h, D.s_now)
base = w * D.s_now.to_numpy() + (1 - w) * s24
y = D.y3.to_numpy(); A = D.A30.to_numpy(); dT = FS * A
res = {"posthoc_coverage": {}}
for per, s0 in [("EVAL1", "2025-07-01"), ("EVAL2", "2026-01-01")]:
    s0 = pd.Timestamp(s0)
    beta = plateau(np.asarray((T >= s0 - pd.DateOffset(months=12)) & (T < s0)))
    rr = np.where(np.abs(A) >= 1, ra, r)
    lo = base + np.minimum(2.5 * beta * dT, 0.5 * beta * dT) - rr
    hi = base + np.maximum(2.5 * beta * dT, 0.5 * beta * dT) + rr
    mid = base + beta * dT
    mm = P[per]; act = mm & (np.abs(A) >= 1)
    res["posthoc_coverage"][per] = {"beta_trailing12": beta, "coverage_all": float(((y >= lo) & (y <= hi))[mm].mean()),
                                    "coverage_action": float(((y >= lo) & (y <= hi))[act].mean()),
                                    "width_action": float((hi - lo)[act].mean()),
                                    "mae_action": float(np.mean(np.abs(y[act] - mid[act]))),
                                    "mae_action_SELECTbeta": float(np.mean(np.abs(y[act] - (base + -0.25 * dT)[act])))}
end = T.max()
res["current_beta_trailing12"] = plateau(np.asarray(T >= end - pd.DateOffset(months=12)), boot=40)
res["current_beta_trailing6"] = plateau(np.asarray(T >= end - pd.DateOffset(months=6)))
res["current_window"] = [str(end - pd.DateOffset(months=12)), str(end)]
# baseline weight and radii re-estimated on the latest data (same procedure: w on older part, radii on last 6 months)
last = D.index >= end - pd.DateOffset(months=18)
old = last & (D.index < end - pd.DateOffset(months=6)); new = D.index >= end - pd.DateOffset(months=6)
wg = np.linspace(0, 1, 21)
w_new = float(wg[np.argmin([np.mean(np.abs(y[old] - (x * D.s_now.to_numpy()[old] + (1 - x) * s24[old]))) for x in wg])])
bn = w_new * D.s_now.to_numpy() + (1 - w_new) * s24
res["current_baseline"] = {"w": w_new, "radius90": float(np.quantile(np.abs(y[new] - bn[new]), .9)),
                           "radius90_action": float(np.quantile(np.abs(y[new & (np.abs(A) >= 1)] - bn[new & (np.abs(A) >= 1)]), .9)),
                           "n_recent": int(new.sum())}
dump("f8_artifact.json", res)
print(json.dumps(res, indent=1))
