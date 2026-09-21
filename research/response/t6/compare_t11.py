"""Like-for-like comparison T11/F26 (old) vs T6/F9 (new) on IDENTICAL 10-min rows. Output out/compare_t11.json.

Rows = intersection of the ARX masks of the old frame (final/response_model.prepare: F26 > 150, F19/F26 band, 307 placeholder)
and the new frame (t6/response_model.prepare). Four tag combinations separate the temperature-tag from the flow-tag effect.
Windows: per half-year (realized), trailing 12 months before 2026-01-01 (C2 artifact window), all rows.
"""
import sys
from tcommon import *
import response_model as rm_new
sys.path.insert(0, str(HERE.parent / "final"))
import importlib.util
spec = importlib.util.spec_from_file_location("rm_old", HERE.parent / "final" / "response_model.py")
rm_old = importlib.util.module_from_spec(spec); spec.loader.exec_module(rm_old)

s, lab, on, ex = load()
# old prepare compares == 307; after load_sources the stubs are NaN -> reproduce the placeholder rule via NaN
s_old = s.copy()
f_old = rm_old.prepare(s_old, on)
f_new = rm_new.prepare(s, on)
f_old["stable"] = f_old.stable_label; f_new["stable"] = f_new.stable_label
combos = {
    "T11_F26_oldrows": (f_old.rename(columns={"T11": "T_in", "F26": "feed"}), "old"),
    "T6_F9_newrows": (f_new.rename(columns={"T6": "T_in", "F9": "feed"}), "new"),
}
# same rows: stable = both rules
both = f_old.stable_label & f_new.stable_label
base = pd.DataFrame({"pak": f_new.pak, "stable": both}, index=s.index)
for name, tcol, fcol in [("T11_F26", "ht.T11", "ht.F26"), ("T6_F9", "ht.T6", "ht.F9"), ("T6_F26", "ht.T6", "ht.F26"), ("T11_F9", "ht.T11", "ht.F9")]:
    g = base.copy(); g["T_in"] = s[tcol]; g["feed"] = s[fcol]
    combos[name + "_samerows"] = (g, "both")
res = {"n_stable_old": int(f_old.stable_label.sum()), "n_stable_new": int(f_new.stable_label.sum()), "n_stable_both": int(both.sum())}
tau = pd.Timestamp("2026-01-01"); cut = tau - rm_new.G
for name, (g, _) in combos.items():
    T, Xm, ym = arx_design(g)
    hv = halves(T)
    row = {"n_rows": int(len(T)),
           "trailing12_tau_2026-01-01": plateau(T, Xm, ym, np.asarray((T > tau - pd.DateOffset(months=12)) & (T <= cut)), boot=40),
           "trailing12_tau_2026-08-07": plateau(T, Xm, ym, np.asarray(T > pd.Timestamp("2026-08-07") - pd.DateOffset(months=12)), boot=40),
           "all": plateau(T, Xm, ym, np.ones(len(T), bool), boot=40),
           "by_half": {h: plateau(T, Xm, ym, hv == h) for h in np.unique(hv)}}
    res[name] = row
    print(name, row["n_rows"], "tr12@2026-01-01", [round(x, 3) for x in row["trailing12_tau_2026-01-01"][:3]],
          "tr12@end", [round(x, 3) for x in row["trailing12_tau_2026-08-07"][:3]], "all", [round(x, 3) for x in row["all"][:3]])
    print("   by half", {k: (round(v, 3) if np.isfinite(v) else None) for k, v in row["by_half"].items()})
dump("compare_t11.json", res)
