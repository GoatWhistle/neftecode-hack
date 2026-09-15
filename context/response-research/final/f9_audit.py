"""F9: audit of the accepted pipeline specification (no new model classes). Output out/f9_audit.json.

(a) past-only vs legacy frozen-PAK flag     (b) rolling baseline weight vs evaluated w = 0.15
(c) consistent radii + next-half coverage    (d) rolling strong multiplier
(e) support / envelope zones on 2025H2 and 2026 states, error by zone on real transitions
(f) current artifact at the end of history   (g) smoke tests of predict()
"""
import sys
from fcommon import *
import response_model as rm

s, lab, on, ex = load()
res = {}
F = {rule: rm.prepare(s, on, frozen_rule=rule) for rule in ("past", "legacy")}
times = F["past"].index[(F["past"].index.minute % 30 == 0)]
times = times[(times >= times[0] + pd.Timedelta("31d")) & (times <= times[-1] - pd.Timedelta("4h"))]
R = {rule: rm.rows(F[rule], times) for rule in F}
f, Rp = F["past"], R["past"]

# (a) frozen flag
a, b = F["past"].pak_frozen, F["legacy"].pak_frozen
res["a_frozen"] = {"share_frozen_past": float(a.mean()), "share_frozen_legacy": float(b.mean()),
                   "share_bins_differ": float((a != b).mean())}
for rule in F:
    Rr = R[rule]; tt = Rr.index + pd.Timedelta("3.5h")
    for per, m in [("EVAL1", (Rr.index >= "2025-07-01 06:00") & (tt < pd.Timestamp("2025-12-31 18:00"))), ("EVAL2", Rr.index >= "2026-01-01 06:00")]:
        mm = m & Rr.train_valid
        base = .15 * Rr.PAK30m + .85 * Rr.PAK24h
        res["a_frozen"][f"{rule}_{per}_baseline_mae_w015"] = float(np.mean(np.abs(Rr.y3[mm] - base[mm])))
        res["a_frozen"][f"{rule}_{per}_n"] = int(mm.sum())
print(res["a_frozen"])

# (b)(c)(d) rolling fits at τ, evaluated on the next half-year
arts = {}
for tau, nxt in [("2025-07-01", "2026-01-01"), ("2026-01-01", "2026-07-01")]:
    art = rm.fit(f, Rp, tau, boot=30)
    arts[tau] = art
    tt = Rp.index + pd.Timedelta("3.5h")
    m = Rp.train_valid & (Rp.index >= pd.Timestamp(tau) + rm.G) & (tt < pd.Timestamp(nxt))
    E = Rp[m]
    out = {"artifact": art.summary(), "n_next": int(m.sum())}
    for label, w, r0, r1, beta, bw, bs in [
            ("rolling_rule", art.w, art.r0, art.r1, art.beta, art.beta_weak, art.beta_strong),
            ("w015_rollingbeta", .15, art.r0, art.r1, art.beta, art.beta_weak, art.beta_strong)]:
        base = w * E.PAK30m + (1 - w) * E.PAK24h
        dT = rm.FS * E.A30
        mid = base + beta * dT
        r = np.where(np.abs(E.A30) >= 1, r1, r0)
        lo = base + np.minimum(bw * dT, bs * dT) - r
        hi = base + np.maximum(bw * dT, bs * dT) + r
        act = np.abs(E.A30) >= 1
        ins = (E.y3 >= lo) & (E.y3 <= hi)
        out[label] = {"mae_all": float(np.mean(np.abs(E.y3 - mid))), "mae_action": float(np.mean(np.abs(E.y3 - mid)[act])),
                      "baseline_mae_all": float(np.mean(np.abs(E.y3 - base))),
                      "coverage_all": float(ins.mean()), "coverage_quiet": float(ins[~act].mean()), "coverage_action": float(ins[act].mean()),
                      "width_action": float((hi - lo)[act].mean()), "n_action": int(act.sum())}
    res[f"tau_{tau}"] = out
    print(tau, json.dumps({k: v for k, v in out.items() if k != "artifact"}, indent=0), art.summary())

# (e) support / zones on next-half states, using the artifact fitted at the half start
zones = {}
err_by_zone = {}
for tau, nxt in [("2025-07-01", "2026-01-01"), ("2026-01-01", "2026-08-08")]:
    art = arts.get(tau) or rm.fit(f, Rp, tau, boot=0)
    m = (Rp.index >= pd.Timestamp(tau) + rm.G) & (Rp.index < pd.Timestamp(nxt)) & Rp.run_past12h
    St = Rp[m].iloc[::4]
    for dT in [-2, -1.5, -1, -0.5, 0.5, 1, 1.5, 2]:
        labs = []
        for t, row in St.iterrows():
            st = {"time": t, **row.to_dict()}
            labs.append(rm.predict(art, st, dT)["zone"])
        zones.setdefault(tau, {})[str(dT)] = pd.Series(labs).value_counts(normalize=True).round(3).to_dict()
    # real transitions: zone for the realized step, factual error/coverage
    Ev = Rp[Rp.train_valid & (Rp.index >= pd.Timestamp(tau) + rm.G) & (Rp.index + pd.Timedelta("3.5h") < pd.Timestamp(nxt)) & (np.abs(Rp.A30) >= .5)]
    for t, row in Ev.iterrows():
        dT = float(np.clip(np.round(row.A30 * 2) / 2, -2, 2))
        pr = rm.predict(art, {"time": t, **row.to_dict()}, dT)
        z = pr["zone"]
        if z == "C_FORBIDDEN":
            err_by_zone.setdefault(z, []).append((np.nan, np.nan)); continue
        delivered = rm.FS * row.A30
        mid = pr["baseline"] + art.beta * delivered
        lo = pr["baseline"] + min(art.beta_weak * delivered, art.beta_strong * delivered) - art.r1
        hi = pr["baseline"] + max(art.beta_weak * delivered, art.beta_strong * delivered) + art.r1
        err_by_zone.setdefault(z, []).append((abs(row.y3 - mid), float(lo <= row.y3 <= hi)))
res["e_zone_share_states"] = zones
res["e_real_transitions_by_zone"] = {z: {"n": len(v), "mae": float(np.nanmean([x[0] for x in v])) if any(np.isfinite(x[0]) for x in v) else None,
                                         "coverage": float(np.nanmean([x[1] for x in v])) if any(np.isfinite(x[1]) for x in v) else None}
                                     for z, v in err_by_zone.items()}
print(json.dumps(zones, indent=1)); print(res["e_real_transitions_by_zone"])

# (f) current artifact
end = f.index[-1]
cur = rm.fit(f, Rp, end, boot=40)
res["f_current_artifact"] = cur.summary()
print(json.dumps(cur.summary(), indent=1, default=str))

# (g) smoke tests
t0 = pd.Timestamp("2026-01-05 08:00")
st0 = rm.live_state(f, t0)
art = arts["2026-01-01"]
preds = {dT: rm.predict(art, st0, dT) for dT in [0, 0.5, 1, 2, 2.5, -1]}
base = art.w * st0["PAK30m"] + (1 - art.w) * st0["PAK24h"]
assert abs(preds[0]["sulfur_mid"] - base) < 1e-9
assert abs(preds[1]["sulfur_mid"] - (base + art.beta)) < 1e-9
assert preds[2.5]["zone"] == "C_FORBIDDEN"
mids = [preds[x]["sulfur_mid"] for x in (-1, 0, 0.5, 1, 2)]
assert all(np.diff(mids) < 0), "not monotone"
frozen_state = dict(st0, pak_frozen_now=True)
assert rm.predict(art, frozen_state, 1)["zone"] == "C_FORBIDDEN"
assert pd.Timestamp(art.windows["beta_10min"][1]) <= pd.Timestamp("2026-01-01")
res["g_smoke"] = {"state": {k: (str(v) if k == "time" else v) for k, v in st0.items()},
                  "artifact_tau": art.tau, "predictions": {str(k): v for k, v in preds.items()}, "asserts": "passed"}
print(json.dumps(res["g_smoke"], indent=1, default=str))
dump("f9_audit.json", res)
