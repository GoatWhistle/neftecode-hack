"""S1 (T6/F9): clean 10-min frame. Output out/frame.pkl.

Tag reading = official 24-2000 dictionary of 16.09 (config/parameters.json control_tags_24_2000):
  T6 inlet of R-202 (action), T11 outlet of R-202, T5 outlet of R-201, F9 mass feed t/h, F15 volumetric feed (scale open),
  F26/F17 hydrotreated DT to shop 8 (vol/mass), P13 inlet pressure, P8 reactor dP, F2 gas flow.
Running filter: F9 above a quantile-based floor (not the old 150 m3/h on F26), T6/T5 > 320, P13 > 3, F2 > 30000, no NaN.
"""
import json

from tcommon import *

s, lab, on, ex = load(refresh=True)
f = pd.DataFrame(index=s.index)
f["T_in"] = s["ht.T6"]
f["T_out"] = s["ht.T11"]
f["T5"] = s["ht.T5"]
f["feed"] = s["ht.F9"]
f["feed_vol"] = s["ht.F15"]
f["prod_vol"] = s["ht.F26"]
f["prod_mass"] = s["ht.F17"]
f["P"] = s["ht.P13"]
f["dP"] = s["ht.P8"]
f["gas2"] = s["ht.F2"]
f["gas22"] = s["ht.F22"]
f["gas25"] = s["ht.F25"]
f["h2oil"] = f.gas2 / f.feed
f["dT_reactor"] = f.T_out - f.T_in
f["density"] = f.feed / f.feed_vol

# PAK on grid (right-labelled), frozen flag past-only (as accepted in round 3)
p = on.set_index("time").value.sort_index()
changed = p.diff().abs().gt(1e-6) | p.diff().isna()
run = changed.cumsum(); t = p.index.to_series()
frozen = (t - t.groupby(run).transform("min")) >= pd.Timedelta("1h")
grid = lambda x, how: x.resample("10min", label="right", closed="right").agg(how).reindex(s.index)
f["pak_raw"] = grid(p, "mean")
f["pak_frozen"] = grid(frozen.astype(float), "max").fillna(1.0).astype(bool)

# Running. Feed floor: quantile of F9 on thermally-running rows (T6, T5 > 320, P13 > 3, F2 > 30000, F9 > 0).
hot = (f.T_in > 320) & (f.T5 > 320) & (f.P > 3.0) & (f.gas2 > 30000) & (f.feed > 0)
FEED_Q = 0.01
feed_floor = float(f.feed[hot].quantile(FEED_Q))
core = ["T_in", "T_out", "T5", "feed", "P", "gas2"]
running = (hot & (f.feed > feed_floor) & f[core].notna().all(axis=1)).to_numpy()
r = pd.Series(running, index=f.index).astype(float)
past = r.rolling("12h").min()
future = r[::-1].rolling(37, min_periods=1).min()[::-1]
f["running"] = running
f["run_past12h"] = past.eq(1)
f["stable"] = (past == 1) & (future == 1)
f["pak"] = f.pak_raw.where(~f.pak_frozen & f.pak_raw.between(0.05, 50))
f.to_pickle(OUT / "frame.pkl")

# comparison with the old (T11/F26) running mask, same data
old_placeholder = s[["ht.T11", "ht.T6", "ht.T5", "ht.F26", "ht.F19", "ht.P13", "ht.F2"]].isna().any(axis=1)
old_running = ((s["ht.F26"] > 150) & (s["ht.T11"] > 320) & (s["ht.T5"] > 320) & (s["ht.P13"] > 3.0) & (s["ht.F2"] > 30000)
               & (s["ht.F19"] / s["ht.F26"]).between(0.75, 0.9) & ~old_placeholder).to_numpy()
summary = {
    "rows": len(f), "feed_floor_t_h": feed_floor, "feed_quantile": FEED_Q,
    "feed_hot_quantiles": f.feed[hot].quantile([.001, .005, .01, .02, .05, .5, .95, .99]).round(2).to_dict(),
    "rows_hot_below_floor": int((hot & (f.feed <= feed_floor)).sum()),
    "running_share": float(f.running.mean()), "stable_share": float(f.stable.mean()),
    "old_running_share": float(old_running.mean()), "running_differs_share": float((running != old_running).mean()),
    "running_new_not_old": int((running & ~old_running).sum()), "running_old_not_new": int((~running & old_running).sum()),
    "pak_valid_share_in_stable": float(f.pak[f.stable].notna().mean()), "pak_frozen_share": float(f.pak_frozen.mean()),
    "stable_by_year": f.stable.groupby(f.index.year).mean().round(3).to_dict(),
    "describe_stable": f.loc[f.stable, ["T_in", "T_out", "T5", "feed", "feed_vol", "prod_vol", "P", "dP", "gas2", "h2oil",
                                        "dT_reactor", "density", "pak"]].describe(percentiles=[.01, .05, .5, .95, .99]).round(3).to_dict(),
    "corr_T6_T11_stable": float(f.loc[f.stable, ["T_in", "T_out"]].corr().iloc[0, 1]),
    "corr_dT6_dT11_stable": float(f.loc[f.stable, ["T_in", "T_out"]].diff().corr().iloc[0, 1]),
}
dump("s1_summary.json", summary)
print(json.dumps({k: v for k, v in summary.items() if k != "describe_stable"}, indent=1, default=str))
print(pd.DataFrame(summary["describe_stable"]).round(2).T)
