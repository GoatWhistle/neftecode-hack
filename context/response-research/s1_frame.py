"""Stage 1/2: clean 10-min frame of HT variables, running mask, PAK trust flags. Output out/frame.pkl.

Tag reading used here (see notes.md, verified on data, NOT the KIP sheet text):
  T11, T6 ~ reactor inlet temperature (°C); T5 ~ reactor outlet / hotter point; F26 volumetric feed (m3/h);
  F19 mass feed (t/h); P13 reactor pressure (MPa); P8 reactor dP; F2 gas (circulating) flow; F22, F25 gas flows.
"""
import json

from common import *

s, lab, on, ex = load()
f = pd.DataFrame(index=s.index)
f["T_in"] = s["ht.T11"]
f["T_in6"] = s["ht.T6"]
f["T_out"] = s["ht.T5"]
f["T23"] = s["ht.T23"]
f["feed"] = s["ht.F26"]
f["feed_mass"] = s["ht.F19"]
f["P"] = s["ht.P13"]
f["dP"] = s["ht.P8"]
f["gas2"] = s["ht.F2"]
f["gas22"] = s["ht.F22"]
f["gas25"] = s["ht.F25"]
f["quench"] = s["ht.F15"]
f["h2oil"] = f.gas2 / f.feed
f["dT_reactor"] = f.T_out - f.T_in

pak = pak_on_grid(on, s.index)
f["pak_raw"] = pak
frozen = flat_mask(on.set_index("time").value, 1.0).reindex(s.index).fillna(True)
f["pak_frozen"] = frozen.to_numpy(bool)

# Running: every core variable in its normal band and not a 307 placeholder.
core = ["T_in", "T_in6", "T_out", "feed", "feed_mass", "P", "gas2"]
placeholder = (s[["ht.T11", "ht.T6", "ht.T5", "ht.F26", "ht.F19", "ht.P13", "ht.F2"]] == 307).any(axis=1).to_numpy()
running = ((f.feed > 150) & (f.T_in > 320) & (f.T_out > 320) & (f.P > 3.0) & (f.gas2 > 30000)
           & (f.feed_mass / f.feed).between(0.75, 0.9)).to_numpy() & ~placeholder
# Stable running: running for the previous 12 h and next 6 h (exclude start-up/shut-down transients).
r = pd.Series(running, index=f.index).astype(float)
past = r.rolling("12h").min()
future = r[::-1].rolling(37, min_periods=1).min()[::-1]
f["running"] = running
f["stable"] = (past == 1) & (future == 1)
f["pak"] = f.pak_raw.where(~f.pak_frozen & f.pak_raw.between(0.05, 50))

f.to_pickle(OUT / "frame.pkl")
summary = {
    "rows": len(f), "running_share": float(f.running.mean()), "stable_share": float(f.stable.mean()),
    "pak_valid_share_in_stable": float(f.pak[f.stable].notna().mean()),
    "pak_frozen_share": float(f.pak_frozen.mean()),
    "stable_by_year": f.stable.groupby(f.index.year).mean().round(3).to_dict(),
    "describe_stable": f.loc[f.stable, ["T_in", "T_in6", "T_out", "feed", "feed_mass", "P", "dP", "gas2", "gas22",
                                        "gas25", "h2oil", "dT_reactor", "pak"]]
        .describe(percentiles=[.01, .05, .5, .95, .99]).round(3).to_dict(),
}
# Shutdown episodes
edges = np.flatnonzero(np.diff(np.r_[0, running.astype(int), 0]))
runs = [(f.index[a], f.index[min(b, len(f) - 1)]) for a, b in zip(edges[::2], edges[1::2])]
gaps = [(str(runs[i][1]), str(runs[i + 1][0]), (runs[i + 1][0] - runs[i][1]).total_seconds() / 3600)
        for i in range(len(runs) - 1)]
summary["gaps_over_6h"] = [g for g in gaps if g[2] > 6]
(OUT / "s1_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str))
print(json.dumps({k: v for k, v in summary.items() if k != "describe_stable"}, indent=1, default=str))
print(pd.DataFrame(summary["describe_stable"]).round(2).T)
