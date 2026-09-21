"""F1b (T6/F9, SELECT only): which ACTION definition and HORIZON. Caches DML residuals for F2/F3.

For action in {A30, A60} and h in {0.5 .. 8}: DML theta = OLS of y~ on (a~, f~) where ~ = cross-fitted residual from state
(nuisance CatBoost, 10 contiguous blocks, 1-day embargo, SELECT rows only). Target Δy = y_h − s_now.
Also: per-period stability (2023 / 2024 / 2025H1), onset subset, first-stage slope Tpath_h ~ A (delivered sustained move),
theta per delivered °C = theta / first_stage. Feedback markers: R²(A | state), corr with past PAK deviation.
"""
import pickle

from tcommon import *

NUIS = ["T_in", "T_out", "T5", "dT_reactor", "feed", "feed_vol", "prod_vol", "P", "dP", "h2oil", "gas2", "gas22", "gas25", "density",
        "T_d6", "feed_d6", "h2oil_d6", "T_trend1h", "T_7d", "T_30d", "T_rel30", "T_rel7", "feed_7d",
        "s_now", "s_jump", "s_1h", "s_6h", "s_24h", "s_dev24", "s_std6h", "lab_s", "lab_s_age_h",
        "ht_in_t95", "ht_in_t95_age_h", "ht_in_t50", "ht_in_ebp", "days_since_restart", "apc_gain14d"]
HS = [0.5, 1, 1.5, 2, 3, 4, 6, 8]
tag = lambda h: str(h).replace(".", "p")

if __name__ == "__main__":
    d = pd.read_pickle(OUT / "ds_final.pkl")
    D = d[d.valid_long].copy()
    tmax = D.index + pd.Timedelta(hours=8.5)
    S = D[periods(tmax, D.index)["SELECT"]].copy()
    assert_select(S.index + pd.Timedelta(hours=8.5))
    S = S[np.isfinite(S[[f"y{tag(h)}" for h in HS]]).all(axis=1) & (S[[f"cov{tag(h)}" for h in HS]] >= .6).all(axis=1)]
    X = S[NUIS]
    cache = {"index": S.index}
    res = {"n_select": len(S)}
    for a in ["A30", "A60", "F30"]:
        cache[a] = S[a].to_numpy() - crossfit(X, S[a].to_numpy())
        res[f"R2_{a}_given_state"] = float(1 - np.var(cache[a]) / np.var(S[a]))
    for h in HS:
        y = (S[f"y{tag(h)}"] - S.s_now).to_numpy()
        cache[f"y{tag(h)}"] = y - crossfit(X, y)
        tp = S[f"Tpath{tag(h)}"].to_numpy()
        cache[f"Tpath{tag(h)}"] = tp - crossfit(X, tp)
    with (OUT / "f1_residuals.pkl").open("wb") as s_:
        pickle.dump({"cache": cache, "S": S}, s_)

    wk = weeks(S.index)
    year = np.where(S.index >= FIT_END, "2025H1", S.index.year.astype(str))
    onset = S.onset.to_numpy()

    def theta(ix, act, yk, draws=250):
        def ols(j):
            A = np.column_stack([cache[act][j], cache["F30"][j], np.ones(len(j))])
            return np.linalg.lstsq(A, cache[yk][j], rcond=None)[0][0]
        est = ols(ix)
        uw = np.unique(wk[ix]); g = {w: ix[wk[ix] == w] for w in uw}
        bs = [ols(np.concatenate([g[w] for w in rng.choice(uw, len(uw))])) for _ in range(draws)]
        return [float(est), float(np.percentile(bs, 5)), float(np.percentile(bs, 95))]

    allix = np.arange(len(S))
    table = {}
    for act in ["A30", "A60"]:
        table[act] = {}
        for h in HS:
            yk = f"y{tag(h)}"
            fs = theta(allix, act, f"Tpath{tag(h)}", draws=100)   # first stage: delivered move per unit action
            row = {"pooled": theta(allix, act, yk), "first_stage": fs,
                   "onset": theta(np.flatnonzero(onset), act, yk)}
            for yy in ["2023", "2024", "2025H1"]:
                row[yy] = theta(np.flatnonzero(year == yy), act, yk)
            row["per_delivered_C"] = row["pooled"][0] / fs[0] if fs[0] > 0.1 else None
            ests = [row[yy][0] for yy in ["2023", "2024", "2025H1"]]
            row["period_spread_ratio"] = float(max(ests) / min(ests)) if all(e < 0 for e in ests) else None
            table[act][str(h)] = row
            print(act, h, {k: (np.round(v, 3).tolist() if isinstance(v, list) else v) for k, v in row.items()})
    res["theta"] = table
    res["feedback_markers"] = {
        a: {"corr_s_dev24": float(np.corrcoef(S[a], S.s_dev24)[0, 1]), "corr_s_jump": float(np.corrcoef(S[a], S.s_jump)[0, 1]),
            "corr_s_jump_onset": float(np.corrcoef(S.loc[S.onset, a], S.loc[S.onset, "s_jump"])[0, 1])} for a in ["A30", "A60"]}
    dump("f1_select.json", res)
    print(json.dumps({k: v for k, v in res.items() if k != "theta"}, indent=1))
