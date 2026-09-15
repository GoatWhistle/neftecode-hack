"""F5: counterfactual sanity (EVAL states), uncertainty with coefficient range, support diagnostic. No refitting.

Live semantics: proposed ΔT = sustained setpoint change (°C). P2/P3 use ΔT directly. P1a/P1b take the historical action
unit A30 = ΔT (initial move). P5 correction takes A30 = ΔT / FS so that its P2 part equals β·ΔT.
Uncertainty rule (fixed on SELECT/VAL): interval = [base + ΔT·β_strong − r, base + ΔT·β_weak + r] (ΔT>0; swapped for ΔT<0),
r = r_VAL if ΔT = 0 else r_VAL_action. Factual check on history uses delivered ΔT = FS·A30.
Support (thresholds fixed a priori): neighbours of (T_in, T_30d, feed, h2oil) within 0.5 SD (SELECT scaling) among SELECT
onset rows with |A30 − ΔT| <= 0.5; IN >= 30, LOW 5–29, OUT < 5; plus T_in+ΔT inside SELECT q01–q99 else OUT.
Output out/f5.json
"""
import pickle

from fcommon import *
from f1_select import NUIS

M_ = pickle.load((OUT / "f4_models.pkl").open("rb"))
BETA, BETA_W, BETA_S = M_["BETA"]   # −0.25, −0.10 (weak), −0.45 (strong)
FS, K = M_["FS"], M_["K"]
d = pd.read_pickle(OUT / "ds_final.pkl")
D = d[d.valid & d.y3.notna() & (d.cov3 >= .6)].copy()
P = periods(D.index + pd.Timedelta(hours=3.5), D.index)
w = M_["blend_w"]
s24 = np.where(np.isfinite(D.s_24h), D.s_24h, D.s_now)
base_all = w * D.s_now.to_numpy() + (1 - w) * s24
X1 = M_["X1"]
res = {}

# ---- sanity grid on EVAL states ----
ev = P["EVAL1"] | P["EVAL2"]
E = D[ev].sample(1500, random_state=0).sort_index()
bE = base_all[D.index.get_indexer(E.index)]
grid = np.array([0, 1, 2, 3, 4])
preds = {}
for name in ["P1a_direct_cb", "P1b_direct_cb_monotone", "P2_additive", "P3_multiplicative", "P5_residual"]:
    rows = []
    for g in grid:
        Z = E.copy()
        if name == "P2_additive":
            rows.append(bE + BETA * g)
        elif name == "P3_multiplicative":
            rows.append(bE * np.exp(-K * g))
        elif name.startswith("P1"):
            Z["A30"] = g
            mdl = M_["p1a"] if name == "P1a_direct_cb" else M_["p1b"]
            rows.append(E.s_now.to_numpy() + mdl.predict(Z[X1]))
        else:
            Z["A30"] = g / FS
            rows.append(bE + BETA * g + M_["p5"].predict(Z[X1]))
    preds[name] = np.array(rows).T      # states × grid
sel = d[d.valid & (d.index < SELECT_END - G)]
Tq01, Tq99 = sel.T_in.quantile([.01, .99])
sanity = {}
for name, Pm in preds.items():
    eff = Pm - Pm[:, [0]]
    d1 = np.diff(Pm, axis=1)
    d2 = np.diff(Pm, n=2, axis=1)
    nxt = np.abs(np.diff(eff[:, 2]))  # neighbour stability of effect(+2) between consecutive sampled states (sorted by time)
    close = np.diff(E.index.asi8) <= pd.Timedelta("1d").value
    sanity[name] = {
        "monotone_share(nonincreasing,tol .01)": float((d1 <= .01).all(axis=1).mean()),
        "strictly_decreasing_share": float((d1 < -1e-6).all(axis=1).mean()),
        "effect_per_C_median": float(np.median(eff[:, 4] / 4)), "effect_+2_q05_q50_q95": np.quantile(eff[:, 2], [.05, .5, .95]).round(3).tolist(),
        "max_abs_second_diff_q95": float(np.quantile(np.abs(d2).max(axis=1), .95)),
        "saturation_ratio_step4_vs_step1_median": float(np.median(d1[:, 3] / np.where(np.abs(d1[:, 0]) > 1e-6, d1[:, 0], np.nan))),
        "neighbour_change_effect+2_median_within_1d": float(np.median(nxt[close])) if close.any() else None,
        "share_T+4_outside_select_q01_q99": float(((E.T_in + 4) > Tq99).mean()),
    }
res["sanity"] = sanity
print(json.dumps(sanity, indent=1))

# ---- uncertainty coverage on EVAL (factual, delivered ΔT = FS·A30) ----
r, ra = M_["radius"]["P2_additive"], M_["radius_action"]["P2_additive"]
A = D.A30.to_numpy(); dT = FS * A; y = D.y3.to_numpy()
mid = base_all + BETA * dT
rr = np.where(np.abs(A) >= 1, ra, r)
lo = base_all + np.minimum(BETA_S * dT, BETA_W * dT) - rr
hi = base_all + np.maximum(BETA_S * dT, BETA_W * dT) + rr
cov = {"r_val": r, "r_val_action": ra}
for per in ["VAL", "EVAL1", "EVAL2"]:
    m = P[per]; act = m & (np.abs(A) >= 1); q = m & (np.abs(A) < .3)
    cov[per] = {"all": float(((y >= lo) & (y <= hi))[m].mean()), "quiet": float(((y >= lo) & (y <= hi))[q].mean()),
                "action": float(((y >= lo) & (y <= hi))[act].mean()), "width_all": float((hi - lo)[m].mean()),
                "width_action": float((hi - lo)[act].mean()), "n_action": int(act.sum())}
res["uncertainty_P2"] = cov
print(json.dumps(cov, indent=1))

# ---- support diagnostic ----
S = d[d.valid & (d.index < SELECT_END - G)]
cols = ["T_in", "T_30d", "feed", "h2oil"]
mu, sd = S[cols].mean(), S[cols].std()
On = S[S.onset]
Zon = ((On[cols] - mu) / sd).to_numpy(); Aon = On.A30.to_numpy()


def support(state, dT):
    if abs(dT) < 1e-9:
        return "IN_SUPPORT", None
    if not (Tq01 <= state["T_in"] + dT <= Tq99):
        return "OUT_OF_SUPPORT", 0
    z = ((pd.Series({c: state[c] for c in cols}) - mu) / sd).to_numpy()
    near = np.sqrt(((Zon - z) ** 2).sum(1)) <= 0.5
    n = int((near & (np.abs(Aon - dT) <= .5)).sum())
    return ("IN_SUPPORT" if n >= 30 else "LOW_SUPPORT" if n >= 5 else "OUT_OF_SUPPORT"), n

share = {}
for g in [1, 2, 3, 4, -1, -2]:
    labs = [support(row, g)[0] for _, row in E.iloc[::3].iterrows()]
    share[str(g)] = pd.Series(labs).value_counts(normalize=True).round(3).to_dict()
res["support_share_eval_states"] = share
# error by label on real EVAL transitions with |A30|>=0.5 (label for delivered move)
Ev = D[ev & (np.abs(D.A30) >= .5)].iloc[::2]
labs = []
for t, row in Ev.iterrows():
    labs.append(support(row, float(np.round(row.A30 * 2) / 2))[0])
Ev = Ev.assign(label=labs)
ii = D.index.get_indexer(Ev.index)
err = np.abs(y[ii] - mid[ii]); inside = (y[ii] >= lo[ii]) & (y[ii] <= hi[ii])
res["support_error_by_label"] = {k: {"n": int((Ev.label == k).sum()), "mae": float(err[(Ev.label == k).to_numpy()].mean()),
                                     "coverage": float(inside[(Ev.label == k).to_numpy()].mean())} for k in Ev.label.unique()}
print(json.dumps({"support_share": share, "error_by_label": res["support_error_by_label"]}, indent=1))

# ---- example states table ----
ex_rows = []
for label, t in [("demo 2026-01-05 08:00", "2026-01-05 08:00"), ("2025-09-15 12:00", "2025-09-15 12:00"),
                 ("high PAK EVAL2", str(D[P['EVAL2']].s_now.idxmax()))]:
    t = pd.Timestamp(t)
    if t not in D.index:
        t = D.index[D.index.get_indexer([t], method="nearest")[0]]
    row = D.loc[t]; b = base_all[D.index.get_loc(t)]
    r0 = []
    for g in [0, 1, 2, 3, 4]:
        rr_ = r if g == 0 else ra
        Z = row.to_frame().T.copy(); Z["A30"] = g
        r0.append({"dT": g, "P2_mid": b + BETA * g, "lo": b + BETA_S * g - rr_, "hi": b + BETA_W * g + rr_,
                   "P1a": float(row.s_now + M_["p1a"].predict(Z[X1].astype(float))[0]),
                   "support": support(row, g)})
    ex_rows.append({"label": label, "time": str(t), "T_in": row.T_in, "s_now": row.s_now, "s_24h": row.s_24h,
                    "base": b, "rows": r0, "realized_y3": row.y3, "realized_A30": row.A30})
res["examples"] = ex_rows
for e in ex_rows:
    print(e["label"], e["time"], "T", round(e["T_in"], 1), "PAK", round(e["s_now"], 2), "base", round(e["base"], 2))
    for q_ in e["rows"]:
        print("   ", q_["dT"], round(q_["P2_mid"], 2), [round(q_["lo"], 2), round(q_["hi"], 2)], "P1a", round(q_["P1a"], 2), q_["support"])
dump("f5.json", res)
