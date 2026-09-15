"""F4: baseline choice (FIT->VAL), candidates P0–P5, evaluation on EVAL-1 / EVAL-2. Main horizon h = 3 h, action A30.

Protocol: learned functions trained on FIT; baseline choice and conformal radius on VAL; response coefficient β from SELECT
(F2 consolidation, frozen here as constants). Nuisance models for orthogonal evaluation trained on full SELECT, applied to EVAL.
Effect unit: live ΔT is a sustained setpoint change. Historical A30 delivers FS = first-stage sustained move at 3 h (F1, SELECT).
  P0 baseline      : base(x)
  P1a direct ML    : CatBoost(x, A30) -> Δy        P1b: same with monotone_constraints (non-increasing in A30)
  P2 additive      : base + β·FS·A30              β = −0.25 ppm/°C, range [−0.10, −0.45]
  P3 multiplicative: base·exp(−k·FS·A30)          k = 0.029
  P4 state-dependent: rejected in F3 (no OOF gain, signs flip across cycles) — not fitted
  P5 residual      : P2 + monotone CatBoost on OOF residual of P2 (FIT)
Output out/f4_candidates.json, out/f4_models.pkl
"""
import pickle
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer

from fcommon import *
from f1_select import NUIS

BETA, BETA_LO, BETA_HI = -0.25, -0.10, -0.45     # per sustained °C (F2)
K_MULT = 0.029
FS = 0.66                                        # F1 first stage A30 -> sustained T at 3 h (SELECT)
MIN = ["s_now", "s_1h", "s_6h", "s_24h", "s_jump", "s_std6h", "lab_s", "lab_s_age_h", "T_in", "T_30d", "T_rel30",
       "feed", "h2oil", "T_trend1h", "days_since_restart"]

d = pd.read_pickle(OUT / "ds_final.pkl")
D = d[d.valid & d.y3.notna() & (d.cov3 >= .6)].copy()
P = periods(D.index + pd.Timedelta(hours=3.5), D.index)
y = D.y3.to_numpy(); s_now = D.s_now.to_numpy(); A = D.A30.to_numpy(); F = D.F30.to_numpy()
dy = y - s_now
res = {"n": {k: int(v.sum()) for k, v in P.items()}}

# ---------------- SELECT stage ----------------
fit, val = P["FIT"], P["VAL"]
assert_select(D.index[fit | val] + pd.Timedelta(hours=3.5))
base_c = {}
base_c["persistence"] = s_now.copy()
w_grid = np.linspace(0, 1, 21)
s24 = np.where(np.isfinite(D.s_24h), D.s_24h, s_now)
w = w_grid[np.argmin([np.mean(np.abs(y[fit] - (ww * s_now[fit] + (1 - ww) * s24[fit]))) for ww in w_grid])]
base_c["blend_now_24h"] = w * s_now + (1 - w) * s24
models = {}
for name, cols, mk in [("ridge_min", MIN, lambda: make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), Ridge(10))),
                       ("cb_min", MIN, lambda: cb(600, 5, .04)), ("cb_full", NUIS, lambda: cb(600, 5, .04))]:
    m = mk().fit(D.loc[fit, cols], dy[fit]); models[name] = (m, cols)
    base_c[name] = s_now + m.predict(D[cols])
res["baseline_val_mae"] = {k: float(np.mean(np.abs(y[val] - v[val]))) for k, v in base_c.items()}
res["baseline_val_mae_quiet"] = {k: float(np.mean(np.abs(y[val & (np.abs(A) < .3)] - v[val & (np.abs(A) < .3)]))) for k, v in base_c.items()}
res["blend_w"] = float(w)
bname = min(res["baseline_val_mae"], key=res["baseline_val_mae"].get)
base = base_c[bname]
res["baseline_selected"] = bname

cand = {"P0_baseline": base}
X1 = NUIS + ["A30"]
p1a = cb(600, 5, .04).fit(D.loc[fit, X1], dy[fit])
p1b = cb(600, 5, .04, monotone_constraints=[0] * len(NUIS) + [-1]).fit(D.loc[fit, X1], dy[fit])
cand["P1a_direct_cb"] = s_now + p1a.predict(D[X1])
cand["P1b_direct_cb_monotone"] = s_now + p1b.predict(D[X1])
cand["P2_additive"] = base + BETA * FS * A
cand["P3_multiplicative"] = base * np.exp(-K_MULT * FS * A)
# P5: OOF residual of P2 on FIT
Dfit = D[fit]
if bname in models:
    m_, cols_ = models[bname]
    oof = s_now[fit] + crossfit(Dfit[cols_], dy[fit], nblocks=8, model=lambda: cb(600, 5, .04))
else:
    oof = base[fit]
resid = y[fit] - (oof + BETA * FS * A[fit])
p5 = cb(400, 4, .04, monotone_constraints=[0] * len(NUIS) + [-1]).fit(Dfit[X1], resid)
cand["P5_residual"] = cand["P2_additive"] + p5.predict(D[X1])

# conformal radius (absolute residual) on VAL per candidate; action-row radius on VAL as well
radius = {k: float(np.quantile(np.abs(y[val] - v[val]), .9)) for k, v in cand.items()}
act_val = val & (np.abs(A) >= 1)
radius_action = {k: float(np.quantile(np.abs(y[act_val] - v[act_val]), .9)) for k, v in cand.items()}
res["radius_val"] = radius; res["radius_val_action"] = radius_action

# nuisance for orthogonal evaluation: trained on SELECT only
sel = P["SELECT"]
nu = {}
for nm, target in [("y", dy), ("a", A), ("f", F)]:
    nu[nm] = cb(400, 5, .05).fit(D.loc[sel, NUIS], target[sel])
with (OUT / "f4_models.pkl").open("wb") as s_:
    pickle.dump({"baseline": bname, "models": models, "blend_w": w, "p1a": p1a, "p1b": p1b, "p5": p5, "nuisance": nu,
                 "radius": radius, "radius_action": radius_action, "X1": X1, "BETA": (BETA, BETA_LO, BETA_HI),
                 "K": K_MULT, "FS": FS}, s_)
print("baseline VAL MAE", res["baseline_val_mae"], "selected", bname)

# ---------------- EVAL stage (no fitting below) ----------------
def local_effect(name, X):
    """Predicted change per +1 unit A30 at the row's state (finite difference around the observed A30)."""
    Xp = X.copy(); Xp["A30"] = X["A30"] + 1
    if name == "P1a_direct_cb":
        return p1a.predict(Xp[X1]) - p1a.predict(X[X1])
    if name == "P1b_direct_cb_monotone":
        return p1b.predict(Xp[X1]) - p1b.predict(X[X1])
    if name == "P5_residual":
        return BETA * FS + p5.predict(Xp[X1]) - p5.predict(X[X1])
    if name == "P2_additive":
        return np.full(len(X), BETA * FS)
    if name == "P3_multiplicative":
        b = base[X.index.get_indexer(X.index)] if False else None
        return None
    return np.zeros(len(X))

wkall = weeks(D.index)
cols_m = ["T_in", "T_30d", "feed", "h2oil", "s_now", "s_jump", "s_dev24", "T_trend1h"]
calip = np.array([1.5, 2.0, 10, 25, .6, .4, .6, .4])
for per in ["VAL", "EVAL1", "EVAL2"]:
    m = P[per]
    E = D[m]
    ye, se, Ae = y[m], s_now[m], A[m]
    ty = dy[m] - nu["y"].predict(E[NUIS]); ta = Ae - nu["a"].predict(E[NUIS]); tf = F[m] - nu["f"].predict(E[NUIS])
    wk = wkall[m]
    # realized orthogonal theta on this period (per A30 and per sustained °C)
    def ols_theta(ix):
        Z = np.column_stack([ta[ix], tf[ix], np.ones(len(ix))]); return np.linalg.lstsq(Z, ty[ix], rcond=None)[0][0]
    ix = np.arange(len(E)); uw = np.unique(wk); g = {u: np.flatnonzero(wk == u) for u in uw}
    est = ols_theta(ix); bs = [ols_theta(np.concatenate([g[u] for u in rng.choice(uw, len(uw))])) for _ in range(300)]
    onset_ix = np.flatnonzero(E.onset.to_numpy())
    est_on = ols_theta(onset_ix)
    out = {"realized_theta_per_A30": [float(est), float(np.percentile(bs, 5)), float(np.percentile(bs, 95))],
           "realized_theta_per_sustained_C": [float(est / FS), float(np.percentile(bs, 5) / FS), float(np.percentile(bs, 95) / FS)],
           "realized_theta_onset_per_A30": float(est_on)}
    # matched pairs inside the period
    Zm = E[cols_m].to_numpy(); tn = E.index.asi8 / 3.6e12; cy = E.cycle_id.to_numpy()
    tr_ = np.flatnonzero(np.abs(Ae) >= 1); co_ = np.flatnonzero(np.abs(Ae) < .3)
    pairs = []
    for i in tr_:
        c_ = co_[(np.abs(tn[co_] - tn[i]) <= 72) & (np.abs(tn[co_] - tn[i]) >= 6) & (cy[co_] == cy[i])]
        if not len(c_): continue
        dz = np.abs(Zm[c_] - Zm[i]) / calip
        ok = np.all(dz <= 1, axis=1) & np.isfinite(dz).all(axis=1)
        if ok.any(): pairs.append((i, c_[ok][np.argmin(dz[ok].sum(1))]))
    pairs = np.array(pairs)
    out["n_pairs"] = int(len(pairs))
    obs_pair = (ye - se)[pairs[:, 0]] - (ye - se)[pairs[:, 1]] if len(pairs) else None
    out["models"] = {}
    for name, pred in cand.items():
        pe = pred[m]
        q = np.abs(Ae) < .3; act = np.abs(Ae) >= 1
        r = radius[name]
        entry = {"mae_all": float(np.mean(np.abs(ye - pe))), "mae_quiet": float(np.mean(np.abs(ye[q] - pe[q]))),
                 "mae_action": float(np.mean(np.abs(ye[act] - pe[act]))),
                 "coverage_all": float((np.abs(ye - pe) <= r).mean()), "coverage_action": float((np.abs(ye[act] - pe[act]) <= r).mean())}
        if name != "P0_baseline":
            if name == "P3_multiplicative":
                le = base[m] * (np.exp(-K_MULT * FS) - 1)
            else:
                le = local_effect(name, E)
            # orthogonal calibration: ty ~ slope*(le*ta) + gamma*tf
            xx = le * ta
            def cal(ix_):
                Z = np.column_stack([xx[ix_], tf[ix_], np.ones(len(ix_))]); return np.linalg.lstsq(Z, ty[ix_], rcond=None)[0][0]
            ce = cal(ix); cb_ = [cal(np.concatenate([g[u] for u in rng.choice(uw, len(uw))])) for _ in range(300)]
            entry["orthogonal_calibration_slope"] = [float(ce), float(np.percentile(cb_, 5)), float(np.percentile(cb_, 95))]
            entry["mean_local_effect_per_A30"] = float(np.mean(le))
            entry["share_rows_effect_nonnegative"] = float((le >= 0).mean())
            if len(pairs):
                pred_pair = (pe - se)[pairs[:, 0]] - (pe - se)[pairs[:, 1]]
                entry["pairs_slope_obs_on_pred"] = slope_ci(pred_pair, obs_pair, wk[pairs[:, 0]], draws=200, intercept=False)
                entry["pairs_sign_concordance"] = float((np.sign(pred_pair) == np.sign(obs_pair)).mean())
                entry["pairs_mae_effect_diff"] = float(np.mean(np.abs(pred_pair - obs_pair)))
        out["models"][name] = entry
    res[per] = out
    print(per, "realized θ/°C", np.round(out["realized_theta_per_sustained_C"], 3), "pairs", out["n_pairs"])
    for name, e in out["models"].items():
        print(f"  {name:24s} MAE {e['mae_all']:.3f} q {e['mae_quiet']:.3f} act {e['mae_action']:.3f} cov {e['coverage_all']:.2f}/{e['coverage_action']:.2f}",
              "" if name == "P0_baseline" else f"calib {np.round(e['orthogonal_calibration_slope'], 2)} eff {e['mean_local_effect_per_A30']:+.3f} "
              f"nonneg {e['share_rows_effect_nonnegative']:.2f} pairs slope {e['pairs_slope_obs_on_pred']['est']:+.2f} "
              f"[{e['pairs_slope_obs_on_pred']['lo']:+.2f},{e['pairs_slope_obs_on_pred']['hi']:+.2f}] sign {e['pairs_sign_concordance']:.2f}")
dump("f4_candidates.json", res)
