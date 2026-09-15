"""F0: recompute the round-1 hybrid honestly (same dataset ds.pkl, same A_cb baseline trained < 2025-01-01).

Leaky version: k_mid=0.035, box [0.015,0.085] (DML over 2023–2026), conformal radius on 2025H2.
Honest version: DML theta on SELECT only (nuisances cross-fitted inside SELECT); k = -theta/mean PAK (SELECT);
box = min/max of 90% CIs of per-period SELECT estimates (2023, 2024, 2025H1); conformal radius on VAL (2025H1).
Evaluate on EVAL-1 (2025H2) and EVAL-2 (2026): action-row MAE, effect calibration slope, interval coverage.
"""
import math

from fcommon import *

d = pd.read_pickle(OUT1 / "ds.pkl")
preds = pd.read_pickle(OUT1 / "s5_preds.pkl")
res = {}

# ---------- SELECT stage: estimate theta per horizon on SELECT only ----------
D0 = d[d.valid].copy()
theta = {}
for h in (2, 3):
    D = D0[D0[f"y{h}"].notna() & (D0[f"y{h}_cov"] >= .5)]
    tt = D.index + pd.Timedelta(hours=h)
    P = periods(tt, D.index)
    S = D[P["SELECT"]]
    assert_select(S.index + pd.Timedelta(hours=h))
    X = S[STATE]
    y = (S[f"y{h}"] - S.s_1h).to_numpy()
    a = S.a_T_in.to_numpy()
    f = S.a_feed_rel.to_numpy()
    yr = y - crossfit(X, y)
    ar = a - crossfit(X, a)
    fr = f - crossfit(X, f)
    wk = weeks(S.index)
    # joint OLS on (ar, fr) like round 1; bootstrap over weeks
    def ols(ix):
        A = np.column_stack([ar[ix], fr[ix], np.ones(len(ix))])
        return np.linalg.lstsq(A, yr[ix], rcond=None)[0][0]
    groups = {}
    for label, m in [("SELECT", np.ones(len(S), bool)), ("2023", S.index.year == 2023), ("2024", S.index.year == 2024),
                     ("2025H1", S.index >= FIT_END)]:
        ix = np.flatnonzero(m)
        est = ols(ix)
        uw = np.unique(wk[ix]); gi = {w: ix[wk[ix] == w] for w in uw}
        bs = [ols(np.concatenate([gi[w] for w in rng.choice(uw, len(uw))])) for _ in range(300)]
        groups[label] = {"theta": float(est), "lo": float(np.percentile(bs, 5)), "hi": float(np.percentile(bs, 95)),
                         "n": int(len(ix))}
    mean_pak = float(S.s_1h.mean())
    theta[h] = {"by_period": groups, "mean_pak_select": mean_pak}
res["select_theta_T_ppm_per_C"] = theta
th3 = theta[3]["by_period"]
k_mid = -th3["SELECT"]["theta"] / theta[3]["mean_pak_select"]
k_lo = max(0.0, -max(v["hi"] for v in th3.values()) / theta[3]["mean_pak_select"])
k_hi = -min(v["lo"] for v in th3.values()) / theta[3]["mean_pak_select"]
res["honest_k"] = {"k_mid": k_mid, "k_lo": k_lo, "k_hi": k_hi,
                   "ppm_per_C_at_mean": [k_lo * theta[3]["mean_pak_select"], k_mid * theta[3]["mean_pak_select"],
                                         k_hi * theta[3]["mean_pak_select"]]}
res["leaky_k"] = {"k_mid": 0.035, "k_lo": 0.015, "k_hi": 0.085}
print(json.dumps(res, indent=1))

# ---------- EVAL stage ----------
for h in (2, 3):
    idx, Pold, y, pr, eff = preds[h]
    D = d.loc[idx]
    P = periods(idx + pd.Timedelta(hours=h), idx)
    base = np.clip(pr["A_cb"], .1, None)
    aT, aF = D.a_T_in.to_numpy(), D.a_feed_rel.to_numpy()
    act = ((np.abs(aT) >= 1) | (np.abs(aF) >= .03))
    out = {}
    for tag, kk in [("leaky", res["leaky_k"]), ("honest", res["honest_k"])]:
        n_mid, n_lo, n_hi = 1.0, 0.4, 3.0   # feed part kept identical in both; only temperature leak is tested here
        mid = base * np.exp(-kk["k_mid"] * aT) * (1 + aF) ** n_mid
        # conformal radius: leaky used 2025H2 (Pold['cal']); honest uses VAL
        cal_mask = Pold["cal"] if tag == "leaky" else P["VAL"]
        r = float(np.quantile(np.abs(np.log(np.clip(y, .1, None)) - np.log(np.clip(mid, .1, None)))[cal_mask], .9))
        edges = np.stack([np.exp(-k * aT) * (1 + aF) ** n for k in (kk["k_lo"], kk["k_hi"]) for n in (n_lo, n_hi)])
        lo, hi = base * edges.min(0) * np.exp(-r), base * edges.max(0) * np.exp(r)
        effect = mid - base
        realized = y - base
        out[tag] = {"radius": r}
        for per in ["EVAL1", "EVAL2"]:
            m = P[per]
            ma = m & act
            big = m & (np.abs(aT) >= 2)
            out[tag][per] = {
                "mae_all": float(np.mean(np.abs(y[m] - mid[m]))),
                "mae_action": float(np.mean(np.abs(y[ma] - mid[ma]))),
                "mae_|aT|>=2": float(np.mean(np.abs(y[big] - mid[big]))),
                "mae_baseline_action": float(np.mean(np.abs(y[ma] - base[ma]))),
                "coverage_all": float(((y >= lo) & (y <= hi))[m].mean()),
                "coverage_action": float(((y >= lo) & (y <= hi))[ma].mean()),
                "width_action": float((hi - lo)[ma].mean()),
                "effect_calibration_slope": slope_ci(effect[ma], realized[ma], weeks(idx[ma]), draws=300),
                "n_action": int(ma.sum()),
            }
    res[f"eval_h{h}"] = out
    print(h, json.dumps(out, indent=1))
dump("f0_leakfix.json", res)
