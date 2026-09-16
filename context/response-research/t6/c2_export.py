"""C2: write config/response_model.json (contract with lane A) from the τ = 2026-01-01 fit on T6/F9."""
from tcommon import *
import response_model as rm

TAU = "2026-01-01"
s, lab, on, ex = load()
f = rm.prepare(s, on)
times = f.index[(f.index.minute % 30 == 0)]
times = times[(times >= times[0] + pd.Timedelta("31d")) & (times <= times[-1] - pd.Timedelta("4h"))]
R = rm.rows(f, times)
art = rm.fit(f, R, TAU, boot=40)
# rows actually used by the ARX in the β window
g = f.rename(columns={"T6": "T_in", "F9": "feed"}); g["stable"] = g.stable_label
T, Xm, ym = arx_design(g)
lo, hi = pd.Timestamp(art.windows["beta_10min"][0]), pd.Timestamp(art.windows["beta_10min"][1])
n_rows = int(((T > lo) & (T <= hi)).sum())
hv = halves(T)
drift = []
for h in sorted(np.unique(hv)):
    b = plateau(T, Xm, ym, hv == h)
    if np.isfinite(b):
        drift.append({"tau": f"{h[:4]}-{'01' if h.endswith('H1') else '07'}-01", "beta": round(float(b), 4)})
fp = json.loads((ROOT / "artifacts/manifest.json").read_text())["fingerprint"]
out = {
    "schema_version": "v1", "tag": "ht.T6", "flow_tag": "ht.F9", "tau": TAU, "window_months": 12,
    "beta_mgkg_per_c": round(float(art.beta), 4), "ci": [round(float(art.beta_ci90[0]), 4), round(float(art.beta_ci90[1]), 4)],
    "envelope_dt_c": 2.0, "n_rows": n_rows,
    "method": (f"ARX(24 lags, 10-min differences of ht.T6, ht.F9, PAK 30-min mean), beta = mean cumulative PAK response at 3-8 h to a "
               f"sustained +1 C step in T6; window ({lo.date()}, {hi}] = 12 months before tau minus 6 h guard; rows = unit running "
               f">=12 h before and 6 h after (T6,T5>320 C, P13>3 MPa, F2>30000, F9>q01={f.attrs['feed_floor']:.1f} t/h, no NaN), "
               f"PAK valid (0.05-50 mg/kg, not frozen >=1 h); ci = month-block bootstrap 90% (40 draws); drift = same ARX per half-year "
               f"starting at tau (realized, not trailing); flow_beta null: F9 lags enter the ARX only as a control, no identified sustained "
               f"flow effect (F9 vs F26 as flow tag changes beta by <0.002); rolling-origin realized/estimate ratio of the trailing-12 rule 0.97-1.71 over 2024H1-2026H1 (bootstrap ci understates next-half uncertainty)"),
    "drift": drift, "flow_beta": None, "model_fingerprint": fp,
    # operating region in which beta applies: q01-q99 of T6 and F9 over the valid history before tau; policy range of beta
    "t6_range_c": [round(float(art.T6_q01), 1), round(float(art.T6_q99), 1)],
    "f9_range_tph": [round(float(art.F9_q01), 1), round(float(art.F9_q99), 1)],
    "weak_strong": [round(float(art.beta_weak), 3), round(float(art.beta_strong), 3)],
}
(ROOT / "config/response_model.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n")
print(json.dumps(out, ensure_ascii=False, indent=1))
