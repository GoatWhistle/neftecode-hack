"""Production forecast F(state) + response βτ·ΔT, validated and recalibrated against laboratory sulfur.

Run from the project root:
    uv run python context/experiments/response_layer_2026-09-15.py
Rules: context/response-layer-2026-09-15.md
"""
import json
import pickle
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(".")
sys.path.insert(0, str(ROOT / "context/response-research/final"))
import response_model as rm  # noqa: E402

from neftecode.application.services.trust import DataTrustAgent  # noqa: E402
from neftecode.infrastructure.data.data import build_features, load_sources  # noqa: E402
from neftecode.infrastructure.ml.forecast import interval, predict_candidate  # noqa: E402

OUT = ROOT / "context/experiments/response-layer-2026-09-15.json"
SEED = 20260915
CAL_MONTHS = 6
LAB_DELAY = pd.Timedelta(hours=4)
PERIODS = {"2025H2": ("2025-07-01", "2026-01-01"), "2026": ("2026-01-01", "2026-09-01")}


def month_start(ts):
    ts = pd.Timestamp(ts)
    return pd.Timestamp(ts.year, ts.month, 1)


def production_forecast(signals, lab, online, bundle, times):
    """F(state) with the production trust / fallback rule, vectorised over decision times."""
    x, meta = build_features(signals, lab, online, list(times), bundle["config"])
    main = predict_candidate(bundle, bundle["selected"], x)
    fallback = predict_candidate(bundle, bundle["fallback"], x)
    agent = DataTrustAgent(bundle["config"])
    value, model, lower, upper = [], [], [], []
    for i in range(len(times)):
        row = meta.iloc[i].to_dict()
        state = {k: (None if (not isinstance(v, (list, dict)) and pd.isna(v)) else
                     (v.isoformat() if isinstance(v, pd.Timestamp) else (v.item() if hasattr(v, "item") else v)))
                 for k, v in row.items()}
        report = agent.assess(state)
        if not report.usable:
            value.append(np.nan); model.append(None); lower.append(np.nan); upper.append(np.nan)
            continue
        name = bundle["fallback"] if report.fallback_mode else bundle["selected"]
        v = float((fallback if report.fallback_mode else main)[i])
        if not np.isfinite(v):
            value.append(np.nan); model.append(name); lower.append(np.nan); upper.append(np.nan)
            continue
        lo, hi = interval(v, bundle["radii"][name])
        value.append(v); model.append(name); lower.append(float(lo)); upper.append(float(hi))
    return np.array(value), model, np.array(lower), np.array(upper)


def t11_mean(t11, end_times, minutes=30):
    rolled = t11.rolling(f"{minutes}min").mean()
    return rolled.reindex(pd.DatetimeIndex(end_times), method="ffill", tolerance=pd.Timedelta("10min")).to_numpy()


def slope(residual, effect, rng):
    ok = np.isfinite(residual) & np.isfinite(effect)
    r, e = residual[ok], effect[ok]
    if len(r) < 8 or np.std(e) == 0:
        return {"n": int(len(r)), "slope": None, "ci90": None}
    def fit(ix):
        A = np.column_stack([np.ones(len(ix)), e[ix]])
        return float(np.linalg.lstsq(A, r[ix], rcond=None)[0][1])
    base = fit(np.arange(len(r)))
    boots = [fit(rng.integers(0, len(r), len(r))) for _ in range(1000)]
    return {"n": int(len(r)), "slope": base, "ci90": [float(np.percentile(boots, 5)), float(np.percentile(boots, 95))]}


def coverage(y, lo, hi):
    ok = np.isfinite(y) & np.isfinite(lo) & np.isfinite(hi)
    if not ok.any():
        return {"n": 0}
    yy, l, h = y[ok], lo[ok], hi[ok]
    risk, alarm = yy > 10, h > 10
    return {"n": int(ok.sum()), "coverage": float(((yy >= l) & (yy <= h)).mean()), "width": float(np.mean(h - l)),
            "exceedances": int(risk.sum()),
            "upper_recall": float(alarm[risk].mean()) if risk.any() else None,
            "upper_false_alarm": float(alarm[~risk].mean()) if (~risk).any() else None,
            "missed": int((risk & ~alarm).sum())}


def mae(y, p):
    ok = np.isfinite(y) & np.isfinite(p)
    return {"n": int(ok.sum()), "mae": float(np.abs(y[ok] - p[ok]).mean()) if ok.any() else None}


def main():
    started = time.time()
    rng = np.random.default_rng(SEED)
    bundle = pickle.load((ROOT / "artifacts/model.pkl").open("rb"))
    signals, lab, online = load_sources(ROOT / "task")
    frame = rm.prepare(signals, online)
    grid = frame.index[frame.index.minute % 30 == 0]
    grid = grid[(grid >= grid[0] + pd.Timedelta("31d")) & (grid <= grid[-1] - pd.Timedelta("4h"))]
    decision_rows = rm.rows(frame, grid)

    samples = lab[(lab.time >= "2025-01-01") & (lab.time < "2026-09-01")].reset_index(drop=True)
    t11 = signals["ht.T11"]
    rows = []
    for h in (3, 2):
        times = samples.time - pd.Timedelta(hours=h)
        value, model, flo, fhi = production_forecast(signals, lab, online, bundle, times)
        before = t11_mean(t11, times)
        after = t11_mean(t11, samples.time)
        rows.append(pd.DataFrame({"h": h, "sample": samples.time, "y": samples.value.to_numpy(float), "t": times,
                                  "F": value, "F_model": model, "F_lo": flo, "F_hi": fhi, "dT_real": after - before}))
    data = pd.concat(rows, ignore_index=True)
    print(f"F готов: {time.time() - started:.0f} с, строк {len(data)}")

    months = sorted({month_start(t) for t in data.t if pd.Timestamp(t) >= pd.Timestamp("2025-01-01")})
    arts = {m: rm.fit(frame, decision_rows, m, boot=0) for m in months}
    print(f"артефакты: {time.time() - started:.0f} с", {str(m.date()): round(a.beta, 3) for m, a in arts.items()})

    beta, bweak, bstrong, zone = [], [], [], []
    for t, d in zip(data.t, data.dT_real):
        art = arts[month_start(t)]
        beta.append(art.beta); bweak.append(art.beta_weak); bstrong.append(art.beta_strong)
        if not np.isfinite(d):
            zone.append("no_T11"); continue
        answer = rm.predict(art, rm.live_state(frame, t), float(round(d, 3)) if abs(d) >= 0.05 else 0.0)
        zone.append(answer["zone"])
    data["beta"], data["beta_weak"], data["beta_strong"], data["zone"] = beta, bweak, bstrong, zone
    applicable = np.isfinite(data.F) & np.isfinite(data.dT_real) & ~data.zone.isin(["C_FORBIDDEN", "no_T11"])
    data["applicable"] = applicable
    data["effect"] = data.beta * data.dT_real
    data["S"] = data.F + data.effect
    data["r"] = data.y - data.S

    # Rolling calibration of the composed interval against laboratory residuals.
    q_lo, q_hi, n_cal = [], [], []
    for _, row in data.iterrows():
        m = month_start(row.t)
        cal = data[(data.h == row.h) & data.applicable & (data["sample"] > m - pd.DateOffset(months=CAL_MONTHS))
                   & (data["sample"] + LAB_DELAY <= m)]
        n_cal.append(len(cal))
        if len(cal) < 60:
            q_lo.append(np.nan); q_hi.append(np.nan); continue
        q_lo.append(float(np.quantile(cal.r, 0.05))); q_hi.append(float(np.quantile(cal.r, 0.95)))
    data["q_lo"], data["q_hi"], data["n_cal"] = q_lo, q_hi, n_cal
    lo_eff = np.minimum(data.beta_weak * data.dT_real, data.beta_strong * data.dT_real)
    hi_eff = np.maximum(data.beta_weak * data.dT_real, data.beta_strong * data.dT_real)
    data["S_lo"] = np.maximum(0.0, data.F + lo_eff + data.q_lo)
    data["S_hi"] = data.F + hi_eff + data.q_hi

    result = {"rules": "context/response-layer-2026-09-15.md", "seconds": None,
              "artifacts": {str(m.date()): {"beta": a.beta, "beta_weak": a.beta_weak, "beta_strong": a.beta_strong}
                            for m, a in arts.items()},
              "periods": {}}
    for period, (a, b) in PERIODS.items():
        for h in (3, 2):
            D = data[(data.h == h) & (data.t >= a) & (data.t < b)]
            A = D[D.applicable]
            y = A.y.to_numpy(float)
            calm = np.abs(A.dT_real.to_numpy()) < 0.25
            act05 = np.abs(A.dT_real.to_numpy()) >= 0.5
            act1 = np.abs(A.dT_real.to_numpy()) >= 1.0
            key = f"{period}_h{h}"
            result["periods"][key] = {
                "samples": int(len(D)), "F_available": int(np.isfinite(D.F).sum()),
                "fallback_rows": int((D.F_model == bundle["fallback"]).sum()),
                "zone_counts": D.zone.value_counts().to_dict(), "applicable": int(len(A)),
                "dT_real_abs_quantiles": [float(np.quantile(np.abs(A.dT_real), q)) for q in (0.5, 0.9, 0.99)] if len(A) else None,
                "mae": {
                    "all": {"F": mae(y, A.F.to_numpy()), "F+effect": mae(y, A.S.to_numpy())},
                    "calm": {"F": mae(y[calm], A.F.to_numpy()[calm]), "F+effect": mae(y[calm], A.S.to_numpy()[calm])},
                    "dT>=0.5": {"F": mae(y[act05], A.F.to_numpy()[act05]), "F+effect": mae(y[act05], A.S.to_numpy()[act05])},
                    "dT>=1": {"F": mae(y[act1], A.F.to_numpy()[act1]), "F+effect": mae(y[act1], A.S.to_numpy()[act1])},
                },
                "calibration_slope_dT>=0.5": slope((A.y - A.F).to_numpy()[act05], A.effect.to_numpy()[act05], rng),
                "composed_interval": {
                    "all": coverage(y, A.S_lo.to_numpy(), A.S_hi.to_numpy()),
                    "calm": coverage(y[calm], A.S_lo.to_numpy()[calm], A.S_hi.to_numpy()[calm]),
                    "dT>=0.5": coverage(y[act05], A.S_lo.to_numpy()[act05], A.S_hi.to_numpy()[act05]),
                },
                "production_F_interval": {
                    "all": coverage(y, A.F_lo.to_numpy(), A.F_hi.to_numpy()),
                    "dT>=0.5": coverage(y[act05], A.F_lo.to_numpy()[act05], A.F_hi.to_numpy()[act05]),
                },
                "q_lo_q_hi_median": [float(np.nanmedian(A.q_lo)), float(np.nanmedian(A.q_hi))] if len(A) else None,
            }
    result["seconds"] = round(time.time() - started, 1)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str))
    for key, r in result["periods"].items():
        m = r["mae"]; c = r["composed_interval"]; p = r["production_F_interval"]; s = r["calibration_slope_dT>=0.5"]
        fmt = lambda d: "—" if d.get("mae") is None else f"{d['mae']:.3f}({d['n']})"
        print(f"{key}: samples {r['samples']} F {r['F_available']} applicable {r['applicable']} zones {r['zone_counts']}")
        print(f"   MAE all F {fmt(m['all']['F'])} S {fmt(m['all']['F+effect'])} | calm F {fmt(m['calm']['F'])} S {fmt(m['calm']['F+effect'])}"
              f" | dT>=0.5 F {fmt(m['dT>=0.5']['F'])} S {fmt(m['dT>=0.5']['F+effect'])} | dT>=1 F {fmt(m['dT>=1']['F'])} S {fmt(m['dT>=1']['F+effect'])}")
        print(f"   slope {s} | q {r['q_lo_q_hi_median']}")
        print(f"   composed cov all {c['all']} | calm {c['calm']} | act {c['dT>=0.5']}")
        print(f"   production F cov all {p['all']} | act {p['dT>=0.5']}")


if __name__ == "__main__":
    main()
