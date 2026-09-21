"""(T6/F9 copy of final/) F2 (SELECT only): cleaner estimates of the sustained temperature effect under APC feedback.

Uses cached cross-fitted residuals from f1_select (SELECT rows only). Horizons 3, 4, 6, 8 h; action A30.
(a) DML pooled, per delivered °C (theta / first stage)
(b) onset subset (no T move, no PAK jump/deviation before t)
(c) APC-gain terciles (past-only 14-day feedback gain)  -> does feedback strength bias theta?
(d) nearest-neighbour matching: treated |A30|>=1 vs control |A30|<0.3, same cycle, within ±3 days, caliper on
    T_in, T_30d, feed, h2oil, s_now, s_jump, s_dev24, T_trend1h; slope of outcome difference on action difference
(e) ARX on 10-min SELECT data (dT, dfeed, dPAK30 lags 4 h), month-block bootstrap
Output out/f2_closed_loop.json
"""
import pickle
from sklearn.linear_model import LinearRegression

from tcommon import *
from f1_select import tag

with (OUT / "f1_residuals.pkl").open("rb") as s_:
    blob = pickle.load(s_)
C, S = blob["cache"], blob["S"]
assert_select(S.index + pd.Timedelta(hours=8.5))
wk = weeks(S.index)
res = {}
HS = [3, 4, 6, 8]


def theta(ix, yk, act="A30", draws=300):
    def ols(j):
        A = np.column_stack([C[act][j], C["F30"][j], np.ones(len(j))])
        return np.linalg.lstsq(A, C[yk][j], rcond=None)[0][0]
    est = ols(ix)
    uw = np.unique(wk[ix]); g = {w: ix[wk[ix] == w] for w in uw}
    bs = [ols(np.concatenate([g[w] for w in rng.choice(uw, len(uw))])) for _ in range(draws)]
    return [float(est), float(np.percentile(bs, 5)), float(np.percentile(bs, 95)), int(len(ix))]


def per_delivered(ix, h):
    t_ = theta(ix, f"y{tag(h)}"); fs = theta(ix, f"Tpath{tag(h)}", draws=150)
    return {"theta_per_A30": t_, "first_stage": fs, "per_delivered_C": t_[0] / fs[0] if fs[0] > .1 else None,
            "per_delivered_range": [t_[1] / fs[0], t_[2] / fs[0]] if fs[0] > .1 else None}

allix = np.arange(len(S))
onset = S.onset.to_numpy()
res["a_pooled"] = {h: per_delivered(allix, h) for h in HS}
res["b_onset"] = {h: per_delivered(np.flatnonzero(onset), h) for h in HS}
g = S.apc_gain14d.to_numpy()
q1, q2 = np.nanquantile(g, [1 / 3, 2 / 3])
res["c_apc_gain_terciles_edges"] = [float(q1), float(q2)]
res["c_apc_gain"] = {}
for lab_, m in [("low", g <= q1), ("mid", (g > q1) & (g <= q2)), ("high", g > q2)]:
    res["c_apc_gain"][lab_] = {h: per_delivered(np.flatnonzero(m & np.isfinite(g)), h) for h in HS}
    res["c_apc_gain"][lab_ + "_onset"] = {h: per_delivered(np.flatnonzero(m & onset & np.isfinite(g)), h) for h in (3, 6)}

# (d) matching
cols = ["T_in", "T_30d", "feed", "h2oil", "s_now", "s_jump", "s_dev24", "T_trend1h"]
cal = {"T_in": 1.5, "T_30d": 2.0, "feed": 10, "h2oil": 25, "s_now": .6, "s_jump": .4, "s_dev24": .6, "T_trend1h": .4}
Z = S[cols].to_numpy()
tnum = S.index.asi8 / 3.6e12  # hours
cyc = S.cycle_id.to_numpy()
A = S.A30.to_numpy()
treated = np.flatnonzero(np.abs(A) >= 1)
controls = np.flatnonzero(np.abs(A) < .3)
scale = np.array([cal[c] for c in cols])
pairs = []
for i in treated:
    cand = controls[(np.abs(tnum[controls] - tnum[i]) <= 72) & (np.abs(tnum[controls] - tnum[i]) >= 6) & (cyc[controls] == cyc[i])]
    if not len(cand):
        continue
    dz = np.abs(Z[cand] - Z[i]) / scale
    ok = np.all(dz <= 1, axis=1) & np.isfinite(dz).all(axis=1)
    if not ok.any():
        continue
    j = cand[ok][np.argmin(dz[ok].sum(1))]
    pairs.append((i, j))
pairs = np.array(pairs)
res["d_matching_pairs"] = int(len(pairs))
res["d_matching"] = {}
if len(pairs) > 30:
    pw = wk[pairs[:, 0]]
    for h in HS:
        yo = (S[f"y{tag(h)}"] - S.s_now).to_numpy()
        tp = S[f"Tpath{tag(h)}"].to_numpy()
        dy = yo[pairs[:, 0]] - yo[pairs[:, 1]]
        da = A[pairs[:, 0]] - A[pairs[:, 1]]
        dtp = tp[pairs[:, 0]] - tp[pairs[:, 1]]
        sl = slope_ci(da, dy, pw, intercept=False)
        fs = slope_ci(da, dtp, pw, intercept=False, draws=150)
        res["d_matching"][h] = {"theta_per_A30": sl, "first_stage": fs,
                               "per_delivered_C": sl["est"] / fs["est"] if fs["est"] > .1 else None,
                               "up_only": slope_ci(da[da > 0], dy[da > 0], pw[da > 0], intercept=False, draws=150),
                               "down_only": slope_ci(da[da < 0], dy[da < 0], pw[da < 0], intercept=False, draws=150)}
    # balance check: pre-treatment differences
    res["d_balance_mean_abs_diff"] = {c: float(np.mean(np.abs(Z[pairs[:, 0], k] - Z[pairs[:, 1], k]))) for k, c in enumerate(cols)}

# (e) ARX on SELECT (10-min)
f = pd.read_pickle(OUT / "frame.pkl")
g10 = f[["T_in", "feed", "pak", "stable"]].copy()
g10["pak"] = g10.pak.rolling("30min").mean()
D10 = g10[["T_in", "feed", "pak"]].diff()
LAGS = 24
Xl = pd.concat({f"{c}_{j}": D10[c].shift(j) for c in ["T_in", "feed", "pak"] for j in range(1, LAGS + 1)}, axis=1)
yl = D10.pak
valid = g10.stable & g10.pak.notna() & g10.stable.shift(LAGS, fill_value=False)
m = valid & Xl.notna().all(axis=1) & yl.notna() & (g10.index < SELECT_END - G)
assert_select(g10.index[m])
Xm, ym = Xl[m].to_numpy(), yl[m].to_numpy()


def step(coef, steps=54):
    b = np.array([coef[j] for j in range(0, LAGS)])
    a = np.array([coef[2 * LAGS + j] for j in range(0, LAGS)])
    u = np.zeros(steps + LAGS); u[LAGS] = 1
    ys = np.zeros(steps + LAGS)
    for t in range(LAGS, steps + LAGS):
        ys[t] = b @ u[t - LAGS:t][::-1] + a @ ys[t - LAGS:t][::-1]
    return np.cumsum(ys[LAGS:])

base = step(LinearRegression().fit(Xm, ym).coef_)
months = np.asarray(g10.index[m].to_period("M").astype(str))
um = np.unique(months); gi = {u: np.flatnonzero(months == u) for u in um}
B = []
for _ in range(60):
    ii = np.concatenate([gi[u] for u in rng.choice(um, len(um))])
    B.append(step(LinearRegression().fit(Xm[ii], ym[ii]).coef_))
B = np.array(B)
res["e_arx_select_step_+1C"] = {f"{k * 10 / 60:g}h": [float(base[k - 1]), float(np.percentile(B[:, k - 1], 5)),
                                                     float(np.percentile(B[:, k - 1], 95))] for k in (3, 6, 9, 12, 18, 24, 36, 48, 54)}
dump("f2_closed_loop.json", res)
print(json.dumps(res, indent=1, default=str))
