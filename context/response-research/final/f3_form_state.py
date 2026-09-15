"""F3 (SELECT only): additive vs multiplicative form; state-dependent effect; catalyst stage.

Orthogonal (DML) residuals from f1: y~ (Δy at h), a~ (A30), f~ (F30). Effect models (per unit A30):
  const      : y~ = θ·a~ + γ·f~ + c
  mult       : y~ = −κ·s_now·a~ + γ·f~ + c                (effect proportional to current sulfur)
  inter(z)   : y~ = (θ0 + θ1·z)·a~ + γ·f~ + c               z standardized on SELECT
Out-of-fold loss on 10 contiguous blocks (fit on 9, score on 1); improvement vs const with week-block bootstrap CI.
Reproducibility: interaction slope θ1 separately in cycle 0 (SELECT part 2023-01..2024-04) and cycle 1 (2024-04..2025-06),
and with a~ × period dummies added. Catalyst: θ by within-cycle stage terciles.
Output out/f3_form_state.json
"""
import pickle

from fcommon import *
from f1_select import tag

with (OUT / "f1_residuals.pkl").open("rb") as s_:
    blob = pickle.load(s_)
C, S = blob["cache"], blob["S"]
assert_select(S.index + pd.Timedelta(hours=8.5))
wk = weeks(S.index)
n = len(S)
blocks = np.array_split(np.arange(n), 10)
per = np.where(S.index >= FIT_END, 2, np.where(S.index.year == 2024, 1, 0))
cyc = S.cycle_id.to_numpy()
res = {}

Z = {}
for c in ["s_now", "T_in", "T_30d", "T_rel30", "feed", "h2oil", "T_d6", "apc_gain14d", "days_since_restart", "s_dev24"]:
    v = S[c].to_numpy(float)
    v = np.where(np.isfinite(v), v, np.nanmedian(v))
    Z[c] = (v - v.mean()) / v.std()
s_now = S.s_now.to_numpy()


def design(kind, ix, a, fz, z=None):
    if kind == "const":
        return np.column_stack([a[ix], fz[ix], np.ones(len(ix))])
    if kind == "mult":
        return np.column_stack([-s_now[ix] * a[ix], fz[ix], np.ones(len(ix))])
    if kind == "inter":
        return np.column_stack([a[ix], z[ix] * a[ix], fz[ix], np.ones(len(ix))])
    raise ValueError


def oof_loss(kind, yk, z=None):
    y, a, fz = C[yk], C["A30"], C["F30"]
    loss = np.full(n, np.nan)
    for b in blocks:
        tr = np.setdiff1d(np.arange(n), b)
        coef = np.linalg.lstsq(design(kind, tr, a, fz, z), y[tr], rcond=None)[0]
        loss[b] = (y[b] - design(kind, b, a, fz, z) @ coef) ** 2
    return loss


def improvement(l_base, l_new, draws=400):
    diff = l_base - l_new    # positive = new better
    uw = np.unique(wk); g = {w: np.flatnonzero(wk == w) for w in uw}
    bs = [diff[np.concatenate([g[w] for w in rng.choice(uw, len(uw))])].mean() for _ in range(draws)]
    return {"mean_gain": float(diff.mean()), "lo": float(np.percentile(bs, 5)), "hi": float(np.percentile(bs, 95)),
            "rel_gain_pct": float(100 * diff.mean() / l_base.mean())}


def fit(ix, yk, z, extra_period=False):
    y, a, fz = C[yk], C["A30"], C["F30"]
    cols = [a[ix], z[ix] * a[ix], fz[ix]]
    if extra_period:
        for p in (1, 2):
            cols.append((per[ix] == p) * a[ix])
    cols.append(np.ones(len(ix)))
    X = np.column_stack(cols)
    est = np.linalg.lstsq(X, y[ix], rcond=None)[0]
    uw = np.unique(wk[ix]); g = {w: ix[wk[ix] == w] for w in uw}
    bs = []
    for _ in range(250):
        j = np.concatenate([g[w] for w in rng.choice(uw, len(uw))])
        cj = [a[j], z[j] * a[j], fz[j]] + ([(per[j] == p) * a[j] for p in (1, 2)] if extra_period else []) + [np.ones(len(j))]
        bs.append(np.linalg.lstsq(np.column_stack(cj), y[j], rcond=None)[0][:2])
    bs = np.array(bs)
    return {"theta0": [float(est[0]), float(np.percentile(bs[:, 0], 5)), float(np.percentile(bs[:, 0], 95))],
            "theta1_per_sd": [float(est[1]), float(np.percentile(bs[:, 1], 5)), float(np.percentile(bs[:, 1], 95))]}

for h in (3, 6):
    yk = f"y{tag(h)}"
    base = oof_loss("const", yk)
    out = {"mult_vs_const": improvement(base, oof_loss("mult", yk))}
    # multiplicative interpretation check: interaction with s_now
    out["inter_s_now_all"] = fit(np.arange(n), yk, Z["s_now"])
    for zname, z in Z.items():
        entry = {"oof_vs_const": improvement(base, oof_loss("inter", yk, z)),
                 "all": fit(np.arange(n), yk, z),
                 "cycle0": fit(np.flatnonzero(cyc == 0), yk, z),
                 "cycle1": fit(np.flatnonzero(cyc == 1), yk, z),
                 "with_period_dummies": fit(np.arange(n), yk, z, extra_period=True)}
        out[f"z_{zname}"] = entry
    res[h] = out
    print("h", h, "mult_vs_const", out["mult_vs_const"])
    for zname in Z:
        e = out[f"z_{zname}"]
        print(f"  {zname:20s} oof {e['oof_vs_const']['rel_gain_pct']:+.3f}% [{e['oof_vs_const']['lo']:+.4f},{e['oof_vs_const']['hi']:+.4f}]"
              f" θ1 all {np.round(e['all']['theta1_per_sd'], 3).tolist()} c0 {np.round(e['cycle0']['theta1_per_sd'], 3).tolist()}"
              f" c1 {np.round(e['cycle1']['theta1_per_sd'], 3).tolist()} +period {np.round(e['with_period_dummies']['theta1_per_sd'], 3).tolist()}")

# Catalyst stage: theta by within-cycle terciles of time in cycle (cycle0: calendar position; cycle1: days since restart)
def theta_sub(ix, yk):
    A = np.column_stack([C["A30"][ix], C["F30"][ix], np.ones(len(ix))])
    est = np.linalg.lstsq(A, C[yk][ix], rcond=None)[0][0]
    uw = np.unique(wk[ix]); g = {w: ix[wk[ix] == w] for w in uw}
    bs = []
    for _ in range(250):
        j = np.concatenate([g[w] for w in rng.choice(uw, len(uw))])
        bs.append(np.linalg.lstsq(np.column_stack([C["A30"][j], C["F30"][j], np.ones(len(j))]), C[yk][j], rcond=None)[0][0])
    return [float(est), float(np.percentile(bs, 5)), float(np.percentile(bs, 95)), int(len(ix))]

cat = {}
for c in (0, 1):
    ix = np.flatnonzero(cyc == c)
    pos = S.index[ix].asi8
    edges = np.quantile(pos, [1 / 3, 2 / 3])
    T30 = S.T_30d.to_numpy()[ix]
    cat[f"cycle{c}"] = {}
    for h in (3, 6):
        yk = f"y{tag(h)}"
        cat[f"cycle{c}"][h] = {
            "early": theta_sub(ix[pos <= edges[0]], yk), "middle": theta_sub(ix[(pos > edges[0]) & (pos <= edges[1])], yk),
            "late": theta_sub(ix[pos > edges[1]], yk),
            "T_30d_by_stage": [float(np.mean(T30[pos <= edges[0]])), float(np.mean(T30[(pos > edges[0]) & (pos <= edges[1])])),
                               float(np.mean(T30[pos > edges[1]]))],
            "dates": [str(pd.Timestamp(S.index[ix][0])), str(pd.Timestamp(edges[0])), str(pd.Timestamp(edges[1])), str(pd.Timestamp(S.index[ix][-1]))]}
    print("catalyst", c, json.dumps(cat[f"cycle{c}"]))
res["catalyst_stage"] = cat
dump("f3_form_state.json", res)
