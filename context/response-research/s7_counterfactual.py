"""Stages 9–11: counterfactual sanity tables, monotonicity/smoothness, support gate, interval coverage.

Output out/s7_counterfactual.json and out/s7_tables.md
"""
import json
import warnings

warnings.filterwarnings("ignore")

import math
from common import *
from response_prototype import HybridResponse, SupportGate, EffectBox

d = pd.read_pickle(OUT / "ds.pkl")
models = pd.read_pickle(OUT / "s5_models.pkl")
preds = pd.read_pickle(OUT / "s5_preds.pkl")
ACTION = ["a_T_in", "a_feed_rel", "a_gas22_k"]
H = 3
res = {}
hyb = HybridResponse()
gate_train = SupportGate(d[d.valid & (d.index < "2025-01-01")])
gate = SupportGate(d[d.valid & (d.index < "2026-01-01")])  # history before test decisions
res["gate_params"] = {"radius": gate.radius, "T_range": gate.T_range, "F_range": gate.F_range,
                      "aT_max": gate.aT_max, "aF_max": gate.aF_max}

GRID = [("HOLD", 0, 0), ("T-2", -2, 0), ("T-1", -1, 0), ("T+1", 1, 0), ("T+2", 2, 0), ("T+3", 3, 0), ("T+4", 4, 0),
        ("T+6", 6, 0), ("feed-10%", 0, -.10), ("feed-5%", 0, -.05), ("feed+5%", 0, .05), ("T+2 & feed-5%", 2, -.05)]


def model_pred(name, row, dT, dF, h=H):
    m, cols = models[h][name]
    z = row.copy()
    z["a_T_in"], z["a_feed_rel"], z["a_gas22_k"] = dT, dF, 0.0
    return float(row["s_1h"] + m.predict(pd.DataFrame([z[cols]]))[0])


def a_pred(row, h=H):
    m, cols = models[h]["A_cb"]
    return float(row["s_1h"] + m.predict(pd.DataFrame([row[cols]]))[0])


# Conformal radius for the hybrid on calibration (log residual), from s5 predictions
idx, P, y, pr, eff = preds[H]
lr = np.abs(np.log(np.clip(y, .1, None)) - np.log(np.clip(pr["H_prior_mech"], .1, None)))
radius = float(np.quantile(lr[P["cal"]], .9))
res["hybrid_log_radius_90"] = radius

valid = d[d.valid]
picks = {
    "demo 2026-01-05 08:00": pd.Timestamp("2026-01-05 08:00"),
    "high sulfur (test max s_1h)": valid[valid.index >= "2026-01-01"].s_1h.idxmax(),
    "fresh catalyst 2024-06-10 08:00": valid[(valid.index >= "2024-06-10") & (valid.index < "2024-06-11")].index[0],
    "hot end of cycle (test max T_in)": valid[valid.index >= "2026-01-01"].T_in.idxmax(),
    "high feed (test max feed)": valid[valid.index >= "2026-01-01"].feed.idxmax(),
}
tables = []
res["tables"] = {}
for label, t in picks.items():
    g_ = gate_train if t < pd.Timestamp("2025-01-01") else gate
    if t not in d.index or not d.loc[t, "valid"]:
        t = valid.index[valid.index.get_indexer([t], method="nearest")[0]]
    row = d.loc[t]
    base = a_pred(row)
    lo_b, hi_b = base * math.exp(-radius), base * math.exp(radius)
    rows = []
    for name, dT, dF in GRID:
        hp = hyb.predict(base, lo_b, hi_b, dT, dF, H)
        sup = g_.assess(row.to_dict(), dT, dF)
        rows.append({"action": name, "B_cb": model_pred("B_cb", row, dT, dF), "B_ridge": model_pred("B_ridge", row, dT, dF),
                     "M_scenario": base * math.exp(-0.085 * dT) * (1 + dF) ** 0.7,
                     "hybrid_mid": hp["mid"], "hybrid_lo": hp["lower"], "hybrid_hi": hp["upper"],
                     "effect_mid": hp["effect_vs_hold_mid"], "effect_range": hp["effect_vs_hold_range"],
                     "support": sup["label"], "analogs": sup["analogs"], "days": sup["analog_days"],
                     "why": "; ".join(x for x in sup["reasons"] if not x.startswith("HOLD"))})
    info = {"time": str(t), "T_in": row.T_in, "feed": row.feed, "s_1h": row.s_1h, "T_rel7d": row.T_rel7d,
            "h2oil": row.h2oil, "actual_y3": row.y3, "actual_aT": row.a_T_in}
    res["tables"][label] = {"state": info, "rows": rows}
    tables.append(f"### {label} — {t}\nstate: T_in {row.T_in:.1f} °C, feed {row.feed:.0f} m3/h, PAK 1h {row.s_1h:.2f}, "
                  f"T−7d mean {row.T_rel7d:+.1f}, H2/oil {row.h2oil:.0f}; realized PAK@3h {row.y3:.2f} (realized aT {row.a_T_in:+.2f})\n\n"
                  "| action | B_cb | B_ridge | scenario | hybrid mid [lo, hi] | effect vs HOLD mid (range) | support (analogs/days) |\n"
                  "|---|---:|---:|---:|---|---|---|\n" +
                  "\n".join(f"| {r['action']} | {r['B_cb']:.2f} | {r['B_ridge']:.2f} | {r['M_scenario']:.2f} | "
                            f"{r['hybrid_mid']:.2f} [{r['hybrid_lo']:.2f}, {r['hybrid_hi']:.2f}] | {r['effect_mid']:+.2f} "
                            f"({r['effect_range'][0]:+.2f}..{r['effect_range'][1]:+.2f}) | {r['support']} ({r['analogs']}/{r['days']})"
                            f"{' — ' + r['why'] if r['why'] else ''} |" for r in rows))

# Monotonicity / smoothness of B models over all test states
test = d[d.valid & (d.index >= "2026-01-01")].sample(400, random_state=0)
Tg = [-3, -2, -1, 0, 1, 2, 3, 4]
Fg = [-.10, -.05, 0, .05, .10]
mono = {}
for name in ["B_cb", "B_ridge"]:
    m, cols = models[H][name]
    PT = []
    for g in Tg:
        z = test.copy(); z["a_T_in"] = g; z["a_feed_rel"] = 0; z["a_gas22_k"] = 0
        PT.append(m.predict(z[cols]))
    PT = np.array(PT).T
    PF = []
    for g in Fg:
        z = test.copy(); z["a_T_in"] = 0; z["a_feed_rel"] = g; z["a_gas22_k"] = 0
        PF.append(m.predict(z[cols]))
    PF = np.array(PF).T
    dTg = np.diff(PT, axis=1)
    dFg = np.diff(PF, axis=1)
    mono[name] = {
        "share_states_T_non_monotone(any increase with T)": float((dTg > 0.02).any(axis=1).mean()),
        "share_states_feed_non_monotone(any decrease with feed)": float((dFg < -0.02).any(axis=1).mean()),
        "median_effect_T+2_vs_HOLD": float(np.median(PT[:, 5] - PT[:, 3])),
        "q05_q95_effect_T+2": [float(np.quantile(PT[:, 5] - PT[:, 3], .05)), float(np.quantile(PT[:, 5] - PT[:, 3], .95))],
        "median_effect_T+4_minus_T+3": float(np.median(PT[:, 7] - PT[:, 6])),
        "max_abs_step_between_adjacent_T": float(np.abs(dTg).max()),
        "median_effect_feed-5%": float(np.median(PF[:, 1] - PF[:, 2])),
        "q05_q95_effect_feed-5%": [float(np.quantile(PF[:, 1] - PF[:, 2], .05)), float(np.quantile(PF[:, 1] - PF[:, 2], .95))],
    }
res["monotonicity_test_states_h3"] = mono

# Interval coverage on test (2026) for hybrid vs B_cb vs scenario, all/quiet/action rows
act = lambda D: ((D.a_T_in.abs() >= 1) | (D.a_feed_rel.abs() >= .03)).to_numpy()
D = d.loc[idx]
cover = {}
box = EffectBox()
for name in ["A_cb", "B_cb", "M_scenario_lag2", "H_prior_mech"]:
    p = np.clip(pr[name], .1, None)
    r = float(np.quantile(np.abs(np.log(np.clip(y, .1, None)) - np.log(p))[P["cal"]], .9))
    lo, hi = p * np.exp(-r), p * np.exp(r)
    if name == "H_prior_mech":
        # widen by effect box edges
        aT, aF = D.a_T_in.to_numpy(), D.a_feed_rel.to_numpy()
        base = np.clip(pr["A_cb"], .1, None)
        rr = np.array([[math.exp(-k * t) * (1 + f) ** n for k in (box.k_lo, box.k_hi) for n in (box.n_lo, box.n_hi)]
                       for t, f in zip(aT, aF)])
        lo, hi = base * rr.min(1) * np.exp(-r), base * rr.max(1) * np.exp(r)
    for sub, m in [("all", np.ones(len(y), bool)), ("quiet", ~act(D)), ("action", act(D))]:
        mm = P["test"] & m
        cover.setdefault(name, {})[sub] = {"coverage": float(((y >= lo) & (y <= hi))[mm].mean()),
                                           "mean_width": float((hi - lo)[mm].mean()), "n": int(mm.sum())}
res["coverage_test_h3_target90"] = cover

# Support label distribution on test for a standard candidate set
labels = {}
sample = d[d.valid & (d.index >= "2026-01-01")].sample(300, random_state=1)
for name, dT, dF in GRID:
    c = pd.Series([gate.assess(r.to_dict(), dT, dF)["label"] for _, r in sample.iterrows()]).value_counts(normalize=True)
    labels[name] = c.round(3).to_dict()
res["support_distribution_test_states"] = labels
# Realized: are UNSUPPORTED real actions harder to predict? (test rows with their realized action)
lab_real = []
Dt = d[d.valid & (d.index >= "2026-01-01") & d.y3.notna()]
for t, r in Dt.iloc[::3].iterrows():
    a3, f3 = r.aT_path3, r.aF_path3
    lab_real.append((t, gate.assess(r.to_dict(), 0.0 if abs(a3) < .5 else a3, 0.0 if abs(f3) < .01 else f3)["label"]))
L = pd.Series(dict(lab_real))
err = pd.Series(np.abs(y - pr["H_prior_mech"]), index=idx)
res["realized_error_by_support_test"] = {k: {"n": int((L == k).sum()), "mae_hybrid": float(err.reindex(L[L == k].index).mean())}
                                         for k in L.unique()}

(OUT / "s7_counterfactual.json").write_text(json.dumps(res, indent=1, default=str))
(OUT / "s7_tables.md").write_text("\n\n".join(tables))
print("\n\n".join(tables))
print(json.dumps({k: res[k] for k in ["gate_params", "hybrid_log_radius_90", "monotonicity_test_states_h3",
                                      "coverage_test_h3_target90", "support_distribution_test_states",
                                      "realized_error_by_support_test"]}, indent=1, default=str))
