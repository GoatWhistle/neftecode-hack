"""F1a: 30-min decision grid dataset for the final study. Output out/ds_final.pkl, out/f1_dataset.json.

All state features use only (.., t]. Action windows start at t. Target windows start AFTER the action window.
  T_now30  = mean T11 (t-30m, t]
  A30      = mean T11 (t, t+30m] - T_now30
  A60      = mean T11 (t, t+60m] - mean T11 (t-60m, t]
  pre_T    = T_now30 - mean T11 (t-90m, t-60m]          (T already moving before t)
  s_now    = mean PAK (t-30m, t];  s_jump = s_now - mean PAK (t-90m, t-30m]
  y{h}     = mean PAK (t+h, t+h+30m], h in 0.5,1,1.5,2,3,4,6,8   (after the 30-min action window)
  Tpath{h} = mean T11 (t+h, t+h+30m] - T_now30                (diagnostic: APC continued moving T)
Catalyst / regime (past only): T_30d (stable mean over 30 d), T_rel30, days_since_restart (stop > 5 d), cycle_id.
APC feedback gain (past only): 14-day rolling slope of hourly [T(τ+3h) − T(τ)] on [PAK_1h(τ) − PAK_24h(τ)], τ+3h <= t.
Setpoint tag: none among the 26 tags of 24-2000 (all T* are process values) -> action is reconstructed from PV.
"""
from fcommon import *

f = pd.read_pickle(OUT1 / "frame.pkl")
s, lab, on, ex = load()
IDX = f.index
M = pd.Timedelta("1min")


def wmean(col, start_min, end_min, times):
    width = int((end_min - start_min) / 10)
    r = f[col].rolling(width, min_periods=max(1, width // 2)).mean()
    return r.reindex(times + end_min * M).to_numpy()


times = IDX[(IDX.minute % 30 == 0)]
times = times[(times >= IDX[0] + pd.Timedelta("31d")) & (times <= IDX[-1] - pd.Timedelta("9h"))]
d = pd.DataFrame(index=times)
for v in ["T_in", "T_out", "feed", "P", "dP", "h2oil", "gas2", "gas22", "gas25", "quench", "dT_reactor", "feed_mass"]:
    d[v] = wmean(v, -30, 0, times)
d["density"] = d.feed_mass / d.feed
d["T_d6"] = d.T_in - wmean("T_in", -390, -360, times)
d["feed_d6"] = d.feed - wmean("feed", -390, -360, times)
d["h2oil_d6"] = d.h2oil - wmean("h2oil", -390, -360, times)
d["T_trend1h"] = d.T_in - wmean("T_in", -90, -60, times)
d["pre_T"] = d.T_trend1h
Ts = f.T_in.where(f.stable)
d["T_7d"] = Ts.rolling("7d", min_periods=300).mean().reindex(times).to_numpy()
d["T_30d"] = Ts.rolling("30d", min_periods=1000).mean().reindex(times).to_numpy()
d["T_rel30"] = d.T_in - d.T_30d
d["T_rel7"] = d.T_in - d.T_7d
d["feed_7d"] = f.feed.where(f.stable).rolling("7d", min_periods=300).mean().reindex(times).to_numpy()
d["s_now"] = wmean("pak", -30, 0, times)
d["s_jump"] = d.s_now - wmean("pak", -90, -30, times)
d["s_1h"] = wmean("pak", -60, 0, times)
d["s_6h"] = wmean("pak", -360, 0, times)
d["s_24h"] = wmean("pak", -1440, 0, times)
d["s_dev24"] = d.s_1h - d.s_24h
d["s_std6h"] = f.pak.rolling(36, min_periods=18).std().reindex(times).to_numpy()

# restarts after stops longer than 5 days
run = f.running.astype(int)
grp = run.ne(run.shift()).cumsum()
stop_len = run.eq(0).groupby(grp).transform("size") * (run == 0)
restart = (run.diff() == 1) & (stop_len.shift(1) >= 5 * 144)
rts = IDX[restart.to_numpy()]
last = pd.Series(rts, index=rts).reindex(times, method="ffill")
d["days_since_restart"] = ((times - last.fillna(IDX[0]).to_numpy()) / pd.Timedelta("1d")).to_numpy()
d["cycle_id"] = np.searchsorted(rts.to_numpy(), times.to_numpy(), side="right")

# LIMS (4 h delay)
def last_lims(frame, name, delay_h=4):
    r = frame.rename(columns={"time": "sample"}).copy()
    r["avail"] = r["sample"] + pd.Timedelta(hours=delay_h)
    j = pd.merge_asof(pd.DataFrame({"t": times}), r.sort_values("avail"), left_on="t", right_on="avail", direction="backward")
    d[name] = j.value.to_numpy()
    d[name + "_age_h"] = ((j.t - j["sample"]).dt.total_seconds() / 3600).to_numpy()
last_lims(lab, "lab_s")
for k in ["ht_in_t95", "ht_in_t50", "ht_in_ebp"]:
    last_lims(ex[k], k)

# APC feedback gain, past only
hh = f[["T_in", "pak", "stable"]].resample("1h", label="right", closed="right").mean()
hs = hh.stable == 1
dev = (hh.pak - hh.pak.rolling("24h").mean()).where(hs)
fut = (hh.T_in.shift(-3) - hh.T_in).where(hs & hs.shift(-3, fill_value=False))
# pair at tau is known at tau+3h -> shift both by 3 h so rolling window ending at t uses only known pairs
x_, y_ = dev.shift(3), fut.shift(3)
ok = x_.notna() & y_.notna()
xx, yy = x_.where(ok), y_.where(ok)
w = "14d"
cov = (xx * yy).rolling(w, min_periods=100).mean() - xx.rolling(w, min_periods=100).mean() * yy.rolling(w, min_periods=100).mean()
var = (xx * xx).rolling(w, min_periods=100).mean() - xx.rolling(w, min_periods=100).mean() ** 2
d["apc_gain14d"] = (cov / var).reindex(times, method="ffill").to_numpy()

# Actions
d["A30"] = wmean("T_in", 0, 30, times) - d.T_in
d["A60"] = wmean("T_in", 0, 60, times) - wmean("T_in", -60, 0, times)
d["F30"] = (wmean("feed", 0, 30, times) - d.feed) / d.feed
HS = [0.5, 1, 1.5, 2, 3, 4, 6, 8]
for h in HS:
    m0 = int(h * 60)
    tag = str(h).replace(".", "p")
    d[f"y{tag}"] = wmean("pak", m0, m0 + 30, times)
    d[f"cov{tag}"] = f.pak.notna().astype(float).rolling(3).mean().reindex(times + (m0 + 30) * M).to_numpy()
    d[f"Tpath{tag}"] = wmean("T_in", m0, m0 + 30, times) - d.T_in

stable = f.stable
okm = np.ones(len(times), bool)
for off in [-420, -60, 0, 30, 60, 120, 180, 210]:
    okm &= stable.reindex(times + off * M).fillna(False).to_numpy(bool)
d["valid"] = okm & d[["s_now", "s_1h", "T_in", "feed", "T_30d", "A30"]].notna().all(axis=1).to_numpy()
d["valid_long"] = d.valid & np.logical_and.reduce([stable.reindex(times + off * M).fillna(False).to_numpy(bool)
                                                    for off in (300, 420, 510)])
d["onset"] = (d.pre_T.abs() < 0.5) & (d.s_jump.abs() < 0.5) & (d.s_dev24.abs() < 1.0)
d.to_pickle(OUT / "ds_final.pkl")

v = d[d.valid]
info = {"rows": len(d), "valid": int(d.valid.sum()), "valid_long": int(d.valid_long.sum()),
        "restarts_gt5d": [str(t) for t in rts], "cycles_in_valid": v.groupby("cycle_id").size().to_dict(),
        "onset_share": float(v.onset.mean()),
        "A30_q": v.A30.quantile([.01, .05, .5, .95, .99]).round(3).to_dict(),
        "share_|A30|>=1": float((v.A30.abs() >= 1).mean()), "share_|A30|>=2": float((v.A30.abs() >= 2).mean()),
        "n_|A30|>=1_onset_by_year": v[(v.A30.abs() >= 1) & v.onset].groupby(v[(v.A30.abs() >= 1) & v.onset].index.year).size().to_dict(),
        "corr_A30_sjump": float(v[["A30", "s_jump"]].corr().iloc[0, 1]),
        "corr_A30_sdev24": float(v[["A30", "s_dev24"]].corr().iloc[0, 1]),
        "corr_A60_sjump": float(v[["A60", "s_jump"]].corr().iloc[0, 1]),
        "corr_A30_sjump_onset": float(v[v.onset][["A30", "s_jump"]].corr().iloc[0, 1]),
        "apc_gain_q": v.apc_gain14d.quantile([.05, .25, .5, .75, .95]).round(3).to_dict(),
        "apc_gain_by_quarter": {str(k): float(x) for k, x in v.apc_gain14d.groupby(v.index.to_period("Q")).median().round(3).items()},
        "Tpath_after_A30>=1_median": {str(h): float(v.loc[v.A30 >= 1, f"Tpath{str(h).replace('.', 'p')}"].median()) for h in HS},
        "Tpath_after_A30<=-1_median": {str(h): float(v.loc[v.A30 <= -1, f"Tpath{str(h).replace('.', 'p')}"].median()) for h in HS},
        }
dump("f1_dataset.json", info)
print(json.dumps(info, indent=1, default=str))
