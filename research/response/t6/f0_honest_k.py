"""F0 analogue (T6/F9): honest multiplicative coefficient k = -beta / mean PAK, for comparison with conversion_per_degree = 0.085
in config/scenarios/baseline.json (ratio = exp(-k*dT)). SELECT-only (DML h3 per delivered C) and trailing-12 at tau = 2026-01-01 (ARX)."""
from tcommon import *

f = pd.read_pickle(OUT / "frame.pkl")
d = pd.read_pickle(OUT / "ds_final.pkl")
sel = json.load((OUT / "f1_select.json").open()); f2 = json.load((OUT / "f2_closed_loop.json").open())
f9 = json.load((OUT / "f9_fit.json").open()); f7 = json.load((OUT / "f7_rolling_origin.json").open())
S = d[d.valid & (d.index + pd.Timedelta("8.5h") < SELECT_END - G)]
mean_sel = float(S.s_1h.mean())
th3 = f2["a_pooled"]["3"]; on3 = f2["b_onset"]["3"]
arx_sel = f2["e_arx_select_step_+1C"]
arx_sel_plateau = float(np.mean([arx_sel[k][0] for k in ("3h", "4h", "6h", "8h")]))
w = f.pak[(f.index > "2025-01-01") & (f.index <= "2025-12-31 18:00") & f.stable]
mean_tr12 = float(w.mean())
beta = f9["tau_2026-01-01"]["artifact"]["beta"]; ci = f9["tau_2026-01-01"]["artifact"]["beta_ci90"]
res = {"config_k_assigned": 0.085,
       "select": {"mean_pak": mean_sel, "dml_h3_per_delivered_C": th3["per_delivered_C"], "dml_h3_range": th3["per_delivered_range"],
                  "onset_h3_per_delivered_C": on3["per_delivered_C"], "arx_select_plateau": arx_sel_plateau,
                  "k_dml": -th3["per_delivered_C"] / mean_sel, "k_dml_range": [-x / mean_sel for x in th3["per_delivered_range"]],
                  "k_arx": -arx_sel_plateau / mean_sel},
       "trailing12_tau_2026-01-01": {"mean_pak_stable": mean_tr12, "beta": beta, "ci": ci, "k": -beta / mean_tr12, "k_ci": [-x / mean_tr12 for x in ci]},
       "note": "k is what exp(-k*dT) needs to reproduce the additive beta at the mean PAK level; the additive form was selected in F3 "
               "(no evidence of proportionality), so k is only a bridge to the current config, not a recommendation of the multiplicative form."}
dump("f0_honest_k.json", res)
print(json.dumps(res, indent=1))
