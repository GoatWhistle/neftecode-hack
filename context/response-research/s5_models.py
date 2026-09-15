"""Stages 6–8, 13: state-only vs state+action vs residual vs mechanistic vs hybrid, temporal validation.

All models predict Δ = y_h − s_1h (PAK level now) and add s_1h back.
Periods by target time: train < 2025-01-01, val 2025H1, cal 2025H2, test >= 2026-01-01 (6 h guard at borders).
Key diagnostic: EFFECT CALIBRATION on action rows. pred_effect = g(s, a) − g(s, 0); realized = y − A(s) with A the
best state-only model. Slope of realized on pred_effect (week-block bootstrap CI): ~1 good, ~0 useless, <0 wrong sign.
Output out/s5_models.json, out/s5_preds.pkl.
"""
import json
import warnings

warnings.filterwarnings("ignore")
from catboost import CatBoostRegressor
from sklearn.linear_model import Ridge, LinearRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer

from common import *

d = pd.read_pickle(OUT / "ds.pkl")
STATE = ["T_in", "T_out", "dT_reactor", "feed", "P", "dP", "h2oil", "gas2", "gas22", "gas25", "quench", "density",
         "T_in_d6", "feed_d6", "h2oil_d6", "gas22_d6", "T_rel7d", "T_in_7d", "feed_7d", "cycle_age_d",
         "s_1h", "s_trend", "s_6h", "s_24h", "s_std6h", "s_last", "lab_s", "lab_s_age_h",
         "ht_in_t95", "ht_in_t95_age_h", "ht_in_t50", "ht_in_ebp", "ht_in_cloud"]
ACTION = ["a_T_in", "a_feed_rel", "a_gas22_k"]
SCEN_K, SCEN_N, SCEN_LAG = 0.085, 0.7, 2.0
rng = np.random.default_rng(0)
out = {"state": STATE, "action": ACTION}


def periods(t):
    return {"train": t < pd.Timestamp("2024-12-31 18:00"),
            "val": (t >= pd.Timestamp("2025-01-01 06:00")) & (t < pd.Timestamp("2025-06-30 18:00")),
            "cal": (t >= pd.Timestamp("2025-07-01 06:00")) & (t < pd.Timestamp("2025-12-31 18:00")),
            "test": t >= pd.Timestamp("2026-01-01 06:00")}


def ridge():
    return make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), Ridge(alpha=10.0))


def cb(seed=0):
    return CatBoostRegressor(iterations=600, depth=5, learning_rate=0.04, loss_function="RMSE", random_seed=seed,
                             thread_count=8, verbose=False, allow_writing_files=False)


def block_bootstrap_slope(x, y, weeks, draws=500):
    x, y = np.asarray(x), np.asarray(y)
    uw = np.unique(weeks)
    groups = {w: np.flatnonzero(weeks == w) for w in uw}
    def slope(ix):
        xx, yy = x[ix], y[ix]
        v = np.var(xx)
        return np.cov(xx, yy)[0, 1] / v if v > 0 else np.nan
    base = slope(np.arange(len(x)))
    bs = []
    for _ in range(draws):
        pick = rng.choice(uw, len(uw))
        bs.append(slope(np.concatenate([groups[w] for w in pick])))
    return {"slope": float(base), "ci90": [float(np.nanpercentile(bs, 5)), float(np.nanpercentile(bs, 95))],
            "corr": float(np.corrcoef(x, y)[0, 1]) if np.std(x) > 0 else None, "n": int(len(x))}


def subset_masks(D):
    return {"all": np.ones(len(D), bool),
            "quiet(|aT|<0.3,|aF|<1%)": ((D.a_T_in.abs() < .3) & (D.a_feed_rel.abs() < .01)).to_numpy(),
            "|aT|>=1": (D.a_T_in.abs() >= 1).to_numpy(), "|aT|>=2": (D.a_T_in.abs() >= 2).to_numpy(),
            "|aF|>=3%": (D.a_feed_rel.abs() >= .03).to_numpy(), "|aF|>=5%": (D.a_feed_rel.abs() >= .05).to_numpy()}


results = {}
preds_all = {}
for h in (1, 2, 3):
    D = d[d.valid & d[f"y{h}"].notna() & (d[f"y{h}_cov"] >= .5)].copy()
    tgt_time = D.index + pd.Timedelta(hours=h)
    P = periods(tgt_time)
    y = D[f"y{h}"].to_numpy()
    base = D.s_1h.to_numpy()
    delta = y - base
    Xs, Xa = D[STATE], D[STATE + ACTION]
    tr = P["train"]
    pr = {"persistence": base.copy()}
    models = {}
    # State-only and state+action
    for name, cols, mk in [("A_ridge", STATE, ridge), ("B_ridge", STATE + ACTION, ridge),
                           ("A_cb", STATE, cb), ("B_cb", STATE + ACTION, cb)]:
        m = mk().fit(D.loc[tr, cols], delta[tr])
        models[name] = (m, cols)
        pr[name] = base + m.predict(D[cols])
    # Out-of-fold A_cb on train (contiguous blocks) for honest residuals
    blocks = np.array_split(np.flatnonzero(tr), 6)
    oof = np.full(len(D), np.nan)
    for b in blocks:
        mask = tr.copy(); mask[b] = False
        mm = cb(1).fit(D.loc[mask, STATE], delta[mask])
        oof[b] = mm.predict(D.iloc[b][STATE])
    A_level = pr["A_cb"].copy()
    A_level[tr] = base[tr] + oof[tr]
    resid = y - A_level
    # R: linear effect on residual of state-only model
    R = LinearRegression().fit(D.loc[tr, ACTION], resid[tr])
    pr["R_linear_on_A"] = pr["A_cb"] + R.predict(D[ACTION]) - R.intercept_ * 0
    # Mechanistic scenario ratio on top of A (exactly as the scenario: effect only after 2 h lag)
    aT, aF = D.a_T_in.to_numpy(), D.a_feed_rel.to_numpy()
    ratio_scen = np.exp(-SCEN_K * aT) * (1 + aF) ** SCEN_N
    pr["M_scenario_lag2"] = pr["A_cb"] * (ratio_scen if h >= SCEN_LAG else 1.0)
    pr["M_scenario_nolag"] = pr["A_cb"] * ratio_scen
    # Hybrid fitted: log(y / A) = -k aT + n log(1+aF) on OOF train, constrained sign via clipping
    pos = (y > 0.3) & (A_level > 0.3)
    Z = np.column_stack([-aT, np.log1p(aF)])
    fit_mask = tr & pos
    lr = LinearRegression().fit(Z[fit_mask], np.log(y[fit_mask] / A_level[fit_mask]))
    k_fit, n_fit = float(lr.coef_[0]), float(lr.coef_[1])
    k_use, n_use = max(k_fit, 0.0), max(n_fit, 0.0)
    pr["H_fitted_mech"] = pr["A_cb"] * np.exp(-k_use * aT) * (1 + aF) ** n_use
    # Hybrid with physics prior (expert/ARX range): k = 0.035 /°C (~0.3 ppm/°C at 8.4), n = 1.0
    pr["H_prior_mech"] = pr["A_cb"] * np.exp(-0.035 * aT) * (1 + aF) ** 1.0
    # Leakage diagnostic: B with path actions (contain later feedback)
    Xp = D[STATE + [f"aT_path{h}", f"aF_path{h}"]]
    mp = cb().fit(Xp[tr], delta[tr])
    pr["B_cb_pathaction(LEAK)"] = base + mp.predict(Xp)

    res = {"n": {k: int(v.sum()) for k, v in P.items()}, "k_fit": k_fit, "n_fit": n_fit,
           "R_coef": dict(zip(ACTION, map(float, R.coef_))), "R_intercept": float(R.intercept_)}
    masks = subset_masks(D)
    # MAE by period and subset
    table = {}
    for per in ["val", "cal", "test"]:
        pm = P[per]
        table[per] = {}
        for name, p in pr.items():
            table[per][name] = {sub: (float(np.mean(np.abs(y[pm & sm] - p[pm & sm]))) if (pm & sm).sum() else None)
                                for sub, sm in masks.items()}
        table[per]["_n"] = {sub: int((pm & sm).sum()) for sub, sm in masks.items()}
    res["mae"] = table
    # Effect calibration on action rows, val+cal+test separately
    effects = {}
    zero = D.copy(); zero[ACTION] = 0.0
    eff = {
        "B_ridge": models["B_ridge"][0].predict(D[STATE + ACTION]) - models["B_ridge"][0].predict(zero[STATE + ACTION]),
        "B_cb": models["B_cb"][0].predict(D[STATE + ACTION]) - models["B_cb"][0].predict(zero[STATE + ACTION]),
        "R_linear_on_A": R.predict(D[ACTION]) - R.predict(np.zeros((1, 3)))[0],
        "M_scenario_lag2": pr["M_scenario_lag2"] - pr["A_cb"],
        "M_scenario_nolag": pr["M_scenario_nolag"] - pr["A_cb"],
        "H_fitted_mech": pr["H_fitted_mech"] - pr["A_cb"],
        "H_prior_mech": pr["H_prior_mech"] - pr["A_cb"],
    }
    realized = y - pr["A_cb"]
    weeks = np.asarray(D.index.to_period("W").astype(str))
    act = (masks["|aT|>=1"] | masks["|aF|>=3%"])
    for per in ["train_oof", "val", "cal", "test"]:
        if per == "train_oof":
            pm, rz = tr & act, y - A_level
        else:
            pm, rz = P[per] & act, realized
        effects[per] = {}
        for name, e in eff.items():
            if np.std(e[pm]) == 0:
                effects[per][name] = {"slope": None, "note": "constant effect (zero lag)"}
                continue
            effects[per][name] = block_bootstrap_slope(e[pm], rz[pm], weeks[pm], draws=300)
        effects[per]["_n_action_rows"] = int(pm.sum())
    res["effect_calibration"] = effects
    # Partial dependence of models on aT (average over test states)
    grid = [-3, -2, -1, 0, 1, 2, 3, 4]
    pdp = {}
    test_states = D[P["test"]]
    for name in ["B_ridge", "B_cb"]:
        m, cols = models[name]
        vals = []
        for g in grid:
            z = test_states.copy(); z["a_T_in"] = g; z["a_feed_rel"] = 0.0; z["a_gas22_k"] = 0.0
            vals.append(float(np.mean(m.predict(z[cols]))))
        pdp[name] = dict(zip(map(str, grid), np.round(np.array(vals) - vals[3], 4).tolist()))
        valsf = []
        for g in [-0.1, -0.05, 0, 0.05, 0.1]:
            z = test_states.copy(); z["a_T_in"] = 0.0; z["a_feed_rel"] = g; z["a_gas22_k"] = 0.0
            valsf.append(float(np.mean(m.predict(z[cols]))))
        pdp[name + "_feed"] = dict(zip(["-10%", "-5%", "0", "+5%", "+10%"], np.round(np.array(valsf) - valsf[2], 4).tolist()))
    res["pdp_test_mean_effect_ppm"] = pdp
    # Ridge coefficient per 1 °C in raw units
    rm = models["B_ridge"][0]
    sc = rm.named_steps["standardscaler"].scale_
    cols = STATE + ACTION
    res["B_ridge_raw_coef"] = {c: float(rm.named_steps["ridge"].coef_[i] / sc[i]) for i, c in enumerate(cols) if c in ACTION}
    results[h] = res
    preds_all[h] = (D.index, P, y, pr, eff, models)
    print(f"\n=== h={h} n={res['n']} k_fit={k_fit:.4f} n_fit={n_fit:.3f} R={res['R_coef']}")
    for per in ["val", "test"]:
        print(per, pd.DataFrame(table[per]).T.round(3).to_string())
    for per in ["train_oof", "val", "cal", "test"]:
        print("effect", per, {k: (v["slope"] if isinstance(v, dict) else v, v.get("ci90") if isinstance(v, dict) else None)
                              for k, v in effects[per].items()})
    print("pdp", pdp, "ridge", res["B_ridge_raw_coef"])

(OUT / "s5_models.json").write_text(json.dumps(results, indent=1, default=str))
pd.to_pickle({h: (v[0], v[1], v[2], v[3], v[4]) for h, v in preds_all.items()}, OUT / "s5_preds.pkl")
pd.to_pickle({h: v[5] for h, v in preds_all.items()}, OUT / "s5_models.pkl")
