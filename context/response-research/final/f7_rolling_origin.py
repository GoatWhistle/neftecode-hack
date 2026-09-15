"""F7: rolling-origin check of how to estimate β for the NEXT half-year (post-hoc question, flagged as such).

For each target half-year H from 2024H1 to 2026H1, using only data before H starts:
  expanding : ARX plateau (3–8 h) on all history before H
  trailing12: ARX plateau on the 12 months before H
  trailing6 : ARX plateau on the 6 months before H
Compared with the realized ARX plateau in H (and the F4/F6 DML estimates). Score = |log ratio| and ratio.
Output out/f7_rolling_origin.json
"""
from sklearn.linear_model import LinearRegression

from fcommon import *

f = pd.read_pickle(OUT1 / "frame.pkl")
g10 = f[["T_in", "feed", "pak", "stable"]].copy(); g10["pak"] = g10.pak.rolling("30min").mean()
D10 = g10[["T_in", "feed", "pak"]].diff(); L = 24
Xl = pd.concat({f"{c}_{j}": D10[c].shift(j) for c in ["T_in", "feed", "pak"] for j in range(1, L + 1)}, axis=1)
m = (g10.stable & g10.pak.notna() & g10.stable.shift(L, fill_value=False) & Xl.notna().all(axis=1) & D10.pak.notna()).to_numpy()
T = g10.index[m]; Xm = Xl.to_numpy()[m]; ym = D10.pak.to_numpy()[m]


def plateau(mask):
    c = LinearRegression().fit(Xm[mask], ym[mask]).coef_
    b, a = c[:L], c[2 * L:3 * L]; u = np.zeros(54 + L); u[L] = 1; ys = np.zeros(54 + L)
    for t in range(L, 54 + L): ys[t] = b @ u[t - L:t][::-1] + a @ ys[t - L:t][::-1]
    return float(np.cumsum(ys[L:])[17:48].mean())

starts = pd.to_datetime(["2024-01-01", "2024-07-01", "2025-01-01", "2025-07-01", "2026-01-01"])
res = {}
for s0 in starts:
    s1 = s0 + pd.DateOffset(months=6)
    realized = plateau(np.asarray((T >= s0) & (T < s1)))
    row = {"realized": realized}
    for name, lo in [("expanding", T[0]), ("trailing12", s0 - pd.DateOffset(months=12)), ("trailing6", s0 - pd.DateOffset(months=6))]:
        est = plateau(np.asarray((T >= lo) & (T < s0)))
        row[name] = {"est": est, "ratio_realized_over_est": realized / est, "abs_log_ratio": abs(np.log(realized / est))}
    res[str(s0.date())] = row
    print(s0.date(), round(realized, 3), {k: (round(v["est"], 3), round(v["ratio_realized_over_est"], 2)) for k, v in row.items() if k != "realized"})
summary = {k: {"mean_abs_log_ratio": float(np.mean([r[k]["abs_log_ratio"] for r in res.values()])),
               "eval_only_2025H2_2026H1": float(np.mean([res[x][k]["abs_log_ratio"] for x in ("2025-07-01", "2026-01-01")]))}
           for k in ("expanding", "trailing12", "trailing6")}
res["summary"] = summary
print(json.dumps(summary, indent=1))
dump("f7_rolling_origin.json", res)
