"""F7 (T6/F9): rolling-origin check of the β window + realized ARX plateau per half-year (drift). Output out/f7_rolling_origin.json."""
from tcommon import *

f = pd.read_pickle(OUT / "frame.pkl")
T, Xm, ym = arx_design(f)
res = {"n_arx_rows": int(len(T))}
hv = halves(T)
res["arx_plateau_by_half"] = {h: plateau(T, Xm, ym, hv == h, boot=40) for h in np.unique(hv)}
res["arx_all"] = plateau(T, Xm, ym, np.ones(len(T), bool), boot=40)
print("by half:", {k: [round(x, 3) if isinstance(x, float) else x for x in v] for k, v in res["arx_plateau_by_half"].items()})
print("all:", res["arx_all"])
starts = pd.to_datetime(["2024-01-01", "2024-07-01", "2025-01-01", "2025-07-01", "2026-01-01"])
ro = {}
for s0 in starts:
    s1 = s0 + pd.DateOffset(months=6)
    realized = plateau(T, Xm, ym, np.asarray((T >= s0) & (T < s1)))
    row = {"realized": realized}
    for name, lo in [("expanding", T[0]), ("trailing12", s0 - pd.DateOffset(months=12)), ("trailing6", s0 - pd.DateOffset(months=6))]:
        est = plateau(T, Xm, ym, np.asarray((T >= lo) & (T < s0)))
        row[name] = {"est": est, "ratio_realized_over_est": realized / est, "abs_log_ratio": abs(np.log(realized / est))}
    ro[str(s0.date())] = row
    print(s0.date(), round(realized, 3), {k: (round(v["est"], 3), round(v["ratio_realized_over_est"], 2)) for k, v in row.items() if k != "realized"})
res["rolling_origin"] = ro
res["summary"] = {k: {"mean_abs_log_ratio": float(np.mean([r[k]["abs_log_ratio"] for r in ro.values()])),
                      "eval_only_2025H2_2026H1": float(np.mean([ro[x][k]["abs_log_ratio"] for x in ("2025-07-01", "2026-01-01")]))}
                  for k in ("expanding", "trailing12", "trailing6")}
print(json.dumps(res["summary"], indent=1))
dump("f7_rolling_origin.json", res)
