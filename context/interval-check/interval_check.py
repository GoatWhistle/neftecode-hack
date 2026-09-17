"""T88: honesty of the last_pak forecast interval. Read-only: model.pkl config, make_dataset, calibrate/interval from src.

1. Coverage of the current radius (bundle radii['last_pak']) by year / half-year 2023-2026.
2. Rolling calibration: for each half-year H (2024H1..2026H1, plus 2026H2 partial) radius = calibrate on rows whose target
   became available in the 6 months before H; coverage / width on rows with decision_time in H.
3. Tank dilution contribution at 2026-01-05 08:00 with old (95 t/h, window 42 h) and new (213 t/h, window 18.7 h) inflow.
Output: context/interval-check/out.json (numbers for context/interval-check-2026-09-17.md).
"""
import json
import math
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from neftecode.infrastructure.data.data import load_sources, make_dataset  # noqa: E402
from neftecode.infrastructure.ml.forecast import calibrate, interval  # noqa: E402

bundle = pickle.load((ROOT / "artifacts/model.pkl").open("rb"))
cfg = bundle["config"]
radius0 = bundle["radii"]["last_pak"]
signals, lab, online = load_sources(ROOT / "task")
x, meta = make_dataset(signals, lab, online, cfg)
y = meta.actual_sulfur.to_numpy(float)
pred = x["pak.sulfur"].to_numpy(float)
dt = pd.DatetimeIndex(meta.decision_time)
avail = pd.DatetimeIndex(meta.target_available_time)
ok = np.isfinite(pred)


def cov_width(mask, radius):
    m = mask & ok
    lo, hi = interval(pred[m], radius)
    inside = (y[m] >= lo) & (y[m] <= hi)
    return {"n": int(mask.sum()), "n_pred": int(m.sum()), "coverage": float(inside.mean()) if m.sum() else None,
            "width": float(np.mean(hi - lo)) if m.sum() else None, "mae": float(np.mean(np.abs(y[m] - pred[m]))) if m.sum() else None}


res = {"radius_current": radius0, "coverage_target": cfg["interval_coverage"], "n_rows": int(len(meta)),
       "calibration_rows": {"period": [cfg["validation_end"], cfg["calibration_end"]]}}
res["current_radius_by_year"] = {str(yr): cov_width(np.asarray(dt.year == yr), radius0) for yr in sorted(set(dt.year))}
hv = np.asarray(dt.year.astype(str)) + np.where(dt.month <= 6, "H1", "H2")
res["current_radius_by_half"] = {h: cov_width(hv == h, radius0) for h in sorted(set(hv))}
# rolling calibration
rolling = {}
for h in ["2024H1", "2024H2", "2025H1", "2025H2", "2026H1", "2026H2"]:
    start = pd.Timestamp(f"{h[:4]}-{'01' if h.endswith('H1') else '07'}-01")
    prev = np.asarray((avail >= start - pd.DateOffset(months=6)) & (avail < start)) & ok
    r = calibrate(y[prev], pred[prev], cfg["interval_coverage"])
    rolling[h] = {"radius_prev6m": float(r), "n_calib": int(prev.sum()), **cov_width(hv == h, r),
                  "coverage_current_radius": res["current_radius_by_half"][h]["coverage"],
                  "width_current_radius": res["current_radius_by_half"][h]["width"]}
res["rolling"] = rolling
# check: reproduce the bundle radius on the calibration period
cal = np.asarray((dt >= pd.Timestamp(cfg["validation_end"])) & (avail < pd.Timestamp(cfg["calibration_end"]))) & ok
res["reproduced_radius_on_calibration"] = float(calibrate(y[cal], pred[cal], cfg["interval_coverage"]))
res["reproduced_test_coverage"] = cov_width(np.asarray(dt >= pd.Timestamp(cfg["calibration_end"])), radius0)
# 4. dilution contribution at 2026-01-05 08:00
when = pd.Timestamp("2026-01-05 08:00")
p = online.set_index("time").value
fc = float(p.reindex([when], method="ffill", tolerance=pd.Timedelta("30min")).iloc[0])   # last_pak forecast = current PAK
lo_, hi_ = interval(np.array([fc]), radius0)
dil = {}
for name, q, M in [("old_95tph", 95.0, 4000.0), ("new_213tph", 212.6, 4000.0), ("new_213tph_M2000", 212.6, 2000.0)]:
    window = M / q
    tank = float(p[(p.index > when - pd.Timedelta(hours=window)) & (p.index <= when)].mean())
    frac = 1 - math.exp(-q * 3 / M)
    dil[name] = {"q_tph": q, "M_t": M, "window_h": round(window, 1), "tank_sulfur_mean_pak_window": round(tank, 3),
                 "forecast_last_pak": round(fc, 3), "forecast_interval": [round(float(lo_[0]), 3), round(float(hi_[0]), 3)],
                 "fraction_renewed_3h": round(frac, 4), "delta_S_3h_mid": round((fc - tank) * frac, 3),
                 "delta_S_3h_interval": [round((float(lo_[0]) - tank) * frac, 3), round((float(hi_[0]) - tank) * frac, 3)]}
res["dilution_2026-01-05T08"] = dil
(Path(__file__).parent / "out.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
print(json.dumps(res, ensure_ascii=False, indent=1))
