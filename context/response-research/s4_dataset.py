"""Stage 3: hourly decision dataset X = state_t + action_(t,t+1h], y = PAK around t+h. Output out/ds.pkl.

State is known at t (past windows only; LIMS with 4 h delivery delay).
Action = mean over (t, t+1h] minus mean over (t-1h, t]: what was done in the next hour.
Leakage variant `aT_path{h}` = mean T over (t+h-1h, t+h] minus T_now (contains later feedback moves; diagnostics only).
Target y{h} = mean valid PAK over (t+h-30min, t+h+30min].
"""
import json

from common import *

f = pd.read_pickle(OUT / "frame.pkl")
s, lab, on, ex = load()
IDX = f.index
H = pd.Timedelta("1h")


def wmean(col: str, start: pd.Timedelta, end: pd.Timedelta, times) -> np.ndarray:
    """Mean of f[col] over (t+start, t+end] for every t (10-min right-labelled grid)."""
    x = f[col]
    width = int((end - start) / pd.Timedelta("10min"))
    r = x.rolling(width, min_periods=max(1, width // 2)).mean()   # mean over the `width` samples ending at label
    return r.reindex(times + end).to_numpy()


times = IDX[(IDX.minute == 0)]
times = times[(times >= IDX[0] + pd.Timedelta("8d")) & (times <= IDX[-1] - pd.Timedelta("5h"))]
d = pd.DataFrame(index=times)
for v in ["T_in", "T_in6", "T_out", "feed", "P", "dP", "h2oil", "gas2", "gas22", "gas25", "quench", "dT_reactor"]:
    d[v] = wmean(v, -H, pd.Timedelta(0), times)
    d[v + "_d6"] = d[v] - wmean(v, -7 * H, -6 * H, times)
d["density"] = wmean("feed_mass", -H, pd.Timedelta(0), times) / d.feed
d["T_in_7d"] = f.T_in.where(f.stable).rolling("7d", min_periods=300).mean().reindex(times).to_numpy()
d["T_rel7d"] = d.T_in - d.T_in_7d
d["feed_7d"] = f.feed.where(f.stable).rolling("7d", min_periods=300).mean().reindex(times).to_numpy()
d["s_1h"] = wmean("pak", -H, pd.Timedelta(0), times)
d["s_prev1h"] = wmean("pak", -2 * H, -H, times)
d["s_trend"] = d.s_1h - d.s_prev1h
d["s_6h"] = wmean("pak", -6 * H, pd.Timedelta(0), times)
d["s_24h"] = wmean("pak", -24 * H, pd.Timedelta(0), times)
d["s_std6h"] = f.pak.rolling(36, min_periods=18).std().reindex(times).to_numpy()
d["s_last"] = f.pak.reindex(times).to_numpy()

# Cycle age: days since the last restart after a stop longer than 24 h
run = f.running.astype(int)
stop_len = run.eq(0).groupby(run.ne(run.shift()).cumsum()).transform("size") * (run == 0)
big_stop_end = (run.diff() == 1) & (stop_len.shift(1) >= 144)
restart_times = IDX[big_stop_end.to_numpy()]
last_restart = pd.Series(restart_times, index=restart_times).reindex(times, method="ffill")
d["cycle_age_d"] = ((times - last_restart.fillna(IDX[0]).to_numpy()) / pd.Timedelta("1d")).to_numpy()

# LIMS with 4 h delay
def last_lims(frame: pd.DataFrame, name: str, delay_h=4):
    r = frame.rename(columns={"time": "sample"}).copy()
    r["avail"] = r["sample"] + pd.Timedelta(hours=delay_h)
    j = pd.merge_asof(pd.DataFrame({"t": times}), r.sort_values("avail"), left_on="t", right_on="avail",
                      direction="backward")
    d[name] = j.value.to_numpy()
    d[name + "_age_h"] = ((j.t - j["sample"]).dt.total_seconds() / 3600).to_numpy()

last_lims(lab, "lab_s")
for k in ["ht_in_t95", "ht_in_t50", "ht_in_ebp", "ht_in_cloud"]:
    last_lims(ex[k], k)

# Actions over the next hour
for v in ["T_in", "feed", "gas22", "h2oil", "T_out"]:
    d["a_" + v] = wmean(v, pd.Timedelta(0), H, times) - d[v]
d["a_feed_rel"] = d.a_feed / d.feed
d["a_gas22_k"] = d.a_gas22 / 1000
for h in (1, 2, 3):
    d[f"y{h}"] = wmean("pak", pd.Timedelta(minutes=60 * h - 30), pd.Timedelta(minutes=60 * h + 30), times)
    d[f"y{h}_cov"] = f.pak.notna().astype(float).rolling(6).mean().reindex(times + pd.Timedelta(minutes=60 * h + 30)).to_numpy()
    d[f"aT_path{h}"] = wmean("T_in", pd.Timedelta(hours=h - 1), pd.Timedelta(hours=h), times) - d.T_in
    d[f"aF_path{h}"] = (wmean("feed", pd.Timedelta(hours=h - 1), pd.Timedelta(hours=h), times) - d.feed) / d.feed

stable = f.stable
ok = np.ones(len(times), bool)
for off in [-7, -3, 0, 1, 2, 3, 4]:
    ok &= stable.reindex(times + pd.Timedelta(hours=off)).fillna(False).to_numpy(bool)
d["valid"] = ok & d.s_1h.notna().to_numpy() & d[["T_in", "feed", "T_in_7d"]].notna().all(axis=1).to_numpy()

d.to_pickle(OUT / "ds.pkl")
v = d[d.valid]
info = {"hours_total": len(d), "valid": int(d.valid.sum()), "by_year": v.groupby(v.index.year).size().to_dict(),
        "restarts": [str(t) for t in restart_times],
        "action_quantiles": v[["a_T_in", "a_feed_rel", "a_gas22_k"]].quantile([.01, .05, .25, .5, .75, .95, .99]).round(4).to_dict(),
        "share_|aT|>=1": float((v.a_T_in.abs() >= 1).mean()), "share_|aT|>=2": float((v.a_T_in.abs() >= 2).mean()),
        "share_|aF|>=3%": float((v.a_feed_rel.abs() >= .03).mean()), "share_|aF|>=5%": float((v.a_feed_rel.abs() >= .05).mean()),
        "n_|aT|>=2_by_year": v[v.a_T_in.abs() >= 2].groupby(v[v.a_T_in.abs() >= 2].index.year).size().to_dict(),
        "n_|aF|>=5%_by_year": v[v.a_feed_rel.abs() >= .05].groupby(v[v.a_feed_rel.abs() >= .05].index.year).size().to_dict(),
        "corr_aT_aF": float(v[["a_T_in", "a_feed_rel"]].corr().iloc[0, 1]),
        "corr_aT_s_trend": float(v[["a_T_in", "s_trend"]].corr().iloc[0, 1]),
        "corr_aT_s_dev24": float(np.corrcoef(v.a_T_in, v.s_1h - v.s_24h)[0, 1]),
        "corr_aF_s_dev24": float(np.corrcoef(v.a_feed_rel, v.s_1h - v.s_24h)[0, 1])}
(OUT / "s4_dataset.json").write_text(json.dumps(info, indent=1, default=str))
print(json.dumps(info, indent=1, default=str))
