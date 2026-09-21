"""(T6/F9 copy of final/) F6: production refit of the response coefficient with the SAME procedure on all history (NOT evaluated; for the artifact).

Per delivered °C: DML (A30, h = 3, 6, 8; nuisance cross-fitted on all valid rows) pooled, onset, per half-year; ARX plateau.
Rule for the artifact (fixed before running): point = ARX plateau (mean of 3–8 h step response);
range = [smallest, largest] magnitude among per-half-year DML point estimates at h3/h6/h8 clipped to at least the ARX CI.
"""
import pickle
from sklearn.linear_model import LinearRegression

from tcommon import *
from f1_select import NUIS, tag

d = pd.read_pickle(OUT / "ds_final.pkl")
D = d[d.valid_long].copy()
HS = [3, 6, 8]
D = D[np.isfinite(D[[f"y{tag(h)}" for h in HS]]).all(axis=1) & (D[[f"cov{tag(h)}" for h in HS]] >= .6).all(axis=1)]
X = D[NUIS]
C = {a: D[a].to_numpy() - crossfit(X, D[a].to_numpy(), nblocks=14) for a in ["A30", "F30"]}
for h in HS:
    y = (D[f"y{tag(h)}"] - D.s_now).to_numpy(); C[f"y{h}"] = y - crossfit(X, y, nblocks=14)
    tp = D[f"Tpath{tag(h)}"].to_numpy(); C[f"T{h}"] = tp - crossfit(X, tp, nblocks=14)
wk = weeks(D.index)
half = np.asarray(D.index.year.astype(str)) + np.where(D.index.month <= 6, "H1", "H2")


def th(ix, yk):
    def ols(j):
        return np.linalg.lstsq(np.column_stack([C["A30"][j], C["F30"][j], np.ones(len(j))]), C[yk][j], rcond=None)[0][0]
    est = ols(ix); uw = np.unique(wk[ix]); g = {w: ix[wk[ix] == w] for w in uw}
    bs = [ols(np.concatenate([g[w] for w in rng.choice(uw, len(uw))])) for _ in range(200)]
    return [float(est), float(np.percentile(bs, 5)), float(np.percentile(bs, 95))]

res = {"per_delivered_C": {}}
allix = np.arange(len(D))
for h in HS:
    fs = th(allix, f"T{h}")[0]
    row = {"first_stage": fs, "pooled": [v / fs for v in th(allix, f"y{h}")],
           "onset": [v / fs for v in th(np.flatnonzero(D.onset.to_numpy()), f"y{h}")]}
    for hh in sorted(np.unique(half)):
        ix = np.flatnonzero(half == hh)
        if len(ix) > 1500:
            row[hh] = [v / fs for v in th(ix, f"y{h}")]
    res["per_delivered_C"][h] = row
    print(h, {k: np.round(v, 3).tolist() if isinstance(v, list) else round(v, 3) for k, v in row.items()})

f = pd.read_pickle(OUT / "frame.pkl")
g10 = f[["T_in", "feed", "pak", "stable"]].copy(); g10["pak"] = g10.pak.rolling("30min").mean()
D10 = g10[["T_in", "feed", "pak"]].diff(); L = 24
Xl = pd.concat({f"{c}_{j}": D10[c].shift(j) for c in ["T_in", "feed", "pak"] for j in range(1, L + 1)}, axis=1)
m = g10.stable & g10.pak.notna() & g10.stable.shift(L, fill_value=False) & Xl.notna().all(axis=1) & D10.pak.notna()
Xm, ym = Xl[m].to_numpy(), D10.pak[m].to_numpy()
def step(c, n=54):
    b, a = c[:L], c[2 * L:3 * L]; u = np.zeros(n + L); u[L] = 1; ys = np.zeros(n + L)
    for t in range(L, n + L): ys[t] = b @ u[t - L:t][::-1] + a @ ys[t - L:t][::-1]
    return np.cumsum(ys[L:])
base = step(LinearRegression().fit(Xm, ym).coef_)
mon = np.asarray(g10.index[m].to_period("M").astype(str)); um = np.unique(mon); gi = {u: np.flatnonzero(mon == u) for u in um}
B = np.array([step(LinearRegression().fit(Xm[ii], ym[ii]).coef_) for ii in
              [np.concatenate([gi[u] for u in rng.choice(um, len(um))]) for _ in range(40)]])
plateau = base[17:48].mean(); pb = B[:, 17:48].mean(1)
res["arx_all_plateau_3_8h"] = [float(plateau), float(np.percentile(pb, 5)), float(np.percentile(pb, 95))]
# ARX by half-year
arx_half = {}
halves = np.asarray(g10.index[m].year.astype(str)) + np.where(g10.index[m].month <= 6, "H1", "H2")
for hh in np.unique(halves):
    ii = np.flatnonzero(halves == hh)
    if len(ii) > 5000:
        arx_half[hh] = float(step(LinearRegression().fit(Xm[ii], ym[ii]).coef_)[17:48].mean())
res["arx_plateau_by_half"] = arx_half
pts = [v[0] for h in HS for k, v in res["per_delivered_C"][h].items() if k[:2] == "20"]
res["artifact_rule"] = {"point": float(plateau), "weak": float(max(max(pts), res["arx_all_plateau_3_8h"][2])),
                        "strong": float(min(min(pts), res["arx_all_plateau_3_8h"][1]))}
# same rule on SELECT-only inputs, for comparison with the evaluated range
sel_pts = [v[0] for h in HS for k, v in res["per_delivered_C"][h].items() if k in ("2023H1", "2023H2", "2024H1", "2024H2", "2025H1")]
res["rule_applied_to_select_halves_only(uses all-data nuisance, indicative)"] = [float(max(sel_pts)), float(min(sel_pts))]
dump("f6_refit_all.json", res)
print(json.dumps({k: v for k, v in res.items() if k != "per_delivered_C"}, indent=1))
