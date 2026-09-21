"""F15 scale check: is k = F15 / (F9 / rho) constant over time? rho = 836.1 kg/m3 (LIMS HT point 2, d15). Output out/f15_scale.json."""
from tcommon import *

s, lab, on, ex = load()
f = pd.read_pickle(OUT / "frame.pkl")
RHO = 0.8361  # t/m3
st = f.stable & (f.feed > 0) & (f.feed_vol > 0)
k = (f.feed_vol / (f.feed / RHO))[st]
res = {"rho_t_m3": RHO, "n": int(st.sum()), "k_median": float(k.median()), "k_q": k.quantile([.01, .05, .25, .5, .75, .95, .99]).round(3).to_dict()}
km = k.resample("MS").median(); kq = k.resample("QS").agg(["median", "std", "count"])
res["k_monthly_median"] = {str(i.date()): round(float(v), 3) for i, v in km.items() if np.isfinite(v)}
res["k_quarterly"] = {str(i.date()): [round(float(r["median"]), 3), round(float(r["std"]), 3), int(r["count"])] for i, r in kq.iterrows() if r["count"] > 0}
# LIMS d15 of feed (point 1) and product (point 2) — actual rho over time
for key in ("ht_in_d15", "ht_out_d15"):
    e = ex[key].set_index("time").value
    e = e[(e > 700) & (e < 950)]
    res[key + "_median"] = float(e.median()); res[key + "_yearly"] = {str(y): round(float(v), 1) for y, v in e.groupby(e.index.year).median().items()}
# which flow does F15 actually track (levels and 10-min diffs, on stable rows)
cand = {"F9": s["ht.F9"], "F26": s["ht.F26"], "F17": s["ht.F17"], "F2": s["ht.F2"], "F22": s["ht.F22"], "F25": s["ht.F25"], "F19": s["ht.F19"]}
res["corr_levels"] = {n: round(float(f.feed_vol[st].corr(c[st])), 3) for n, c in cand.items()}
res["corr_diffs"] = {n: round(float(f.feed_vol[st].diff().corr(c[st].diff())), 3) for n, c in cand.items()}
res["corr_1h_diffs"] = {n: round(float(f.feed_vol[st].diff(6).corr(c[st].diff(6))), 3) for n, c in cand.items()}
res["ratio_F15_over_F9_median"] = float((f.feed_vol / f.feed)[st].median())
res["ratio_F15_over_F9_yearly"] = {str(y): round(float(v), 3) for y, v in (f.feed_vol / f.feed)[st].groupby(f.index[st].year).median().items()}
res["ratio_F15_over_F26_median"] = float((f.feed_vol / f.prod_vol)[st].median())
# regression F15 ~ a + b*F9 per year (is it affine rather than proportional?)
res["affine_by_year"] = {}
for y, g in f[st].groupby(f.index[st].year):
    b, a = np.polyfit(g.feed, g.feed_vol, 1)
    res["affine_by_year"][str(y)] = {"slope": round(float(b), 3), "intercept": round(float(a), 1), "r": round(float(g.feed.corr(g.feed_vol)), 3)}
dump("f15_scale.json", res)
print(json.dumps(res, indent=1, ensure_ascii=False))
