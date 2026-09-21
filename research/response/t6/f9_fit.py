"""F9 (T6/F9): rolling fits of the accepted pipeline with T6 as reactor inlet and F9 as feed. Output out/f9_fit.json.

Same code path as final/f9_audit.py (b)(c)(d)(f): fit at τ, evaluate on the next half-year, current artifact at end of data.
τ list: 2025-07-01, 2026-01-01 (C2 artifact), 2026-07-01, end of history 2026-08-07.
"""
import time

from tcommon import *
import response_model as rm

t0 = time.time()
s, lab, on, ex = load()
f = rm.prepare(s, on)
times = f.index[(f.index.minute % 30 == 0)]
times = times[(times >= times[0] + pd.Timedelta("31d")) & (times <= times[-1] - pd.Timedelta("4h"))]
R = rm.rows(f, times)
res = {"feed_floor": f.attrs["feed_floor"], "n_rows_30min": int(len(R)), "n_train_valid": int(R.train_valid.sum()),
       "prep_seconds": round(time.time() - t0, 1)}
print(res)


def evaluate(art, tau, nxt):
    tt = R.index + pd.Timedelta("3.5h")
    m = R.train_valid & (R.index >= pd.Timestamp(tau) + rm.G) & (tt < pd.Timestamp(nxt))
    E = R[m]
    if len(E) == 0:
        return {"n_next": 0}
    base = art.w * E.PAK30m + (1 - art.w) * E.PAK24h
    dT = rm.FS * E.A30
    mid = base + art.beta * dT
    r = np.where(np.abs(E.A30) >= 1, art.r1, art.r0)
    lo = base + np.minimum(art.beta_weak * dT, art.beta_strong * dT) - r
    hi = base + np.maximum(art.beta_weak * dT, art.beta_strong * dT) + r
    act = np.abs(E.A30) >= 1
    ins = (E.y3 >= lo) & (E.y3 <= hi)
    return {"n_next": int(m.sum()), "mae_all": float(np.mean(np.abs(E.y3 - mid))), "mae_action": float(np.mean(np.abs(E.y3 - mid)[act])),
            "baseline_mae_all": float(np.mean(np.abs(E.y3 - base))), "baseline_mae_action": float(np.mean(np.abs(E.y3 - base)[act])),
            "coverage_all": float(ins.mean()), "coverage_quiet": float(ins[~act].mean()), "coverage_action": float(ins[act].mean()),
            "width_action": float((hi - lo)[act].mean()), "n_action": int(act.sum()),
            "realized_slope_action": slope_ci((art.beta * dT)[act], (E.y3 - base)[act], weeks(E.index[act]), draws=300)}


for tau, nxt, boot in [("2025-07-01", "2026-01-01", 40), ("2026-01-01", "2026-07-01", 40), ("2026-07-01", "2026-08-08", 40),
                       (str(f.index[-1]), None, 40)]:
    t1 = time.time()
    art = rm.fit(f, R, tau, boot=boot)
    out = {"artifact": art.summary(), "fit_seconds": round(time.time() - t1, 1)}
    if nxt:
        out["next_half"] = evaluate(art, tau, nxt)
    res[f"tau_{tau[:10]}"] = out
    print(tau, "beta", round(art.beta, 4), art.beta_ci90, "w", art.w, "r0/r1", round(art.r0, 2), round(art.r1, 2),
          "strong", round(art.beta_strong, 3), "ratios", art.past_ratios, "n10min", art.windows, f"{out['fit_seconds']}s")
    if nxt:
        print("  next:", {k: (round(v, 3) if isinstance(v, float) else v) for k, v in out["next_half"].items() if k != "realized_slope_action"},
              out["next_half"].get("realized_slope_action"))

# smoke: state 2026-01-05 08:00 with τ = 2026-01-01 artifact
art = rm.fit(f, R, "2026-01-01", boot=0)
st0 = rm.live_state(f, pd.Timestamp("2026-01-05 08:00"))
preds = {str(dT): rm.predict(art, st0, dT) for dT in [0, 0.5, 1, 2, 2.5, -1]}
res["smoke_2026-01-05T08"] = {"state": {k: (str(v) if k == "time" else v) for k, v in st0.items()}, "predictions": preds}
print(json.dumps(res["smoke_2026-01-05T08"], indent=1, default=str))
res["total_seconds"] = round(time.time() - t0, 1)
dump("f9_fit.json", res)
