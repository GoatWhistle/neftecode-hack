"""Old forecast vs the response-model baseline, both scored on the same 2026 laboratory samples.

Run from the project root:
    uv run python context/experiments/response_vs_lims_2026-09-15.py
Rules: context/response-vs-lims-2026-09-15.md
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(".")
sys.path.insert(0, str(ROOT / "context/response-research/final"))
import response_model as rm  # noqa: E402

from neftecode.infrastructure.data.data import load_sources  # noqa: E402
from neftecode.infrastructure.ml.forecast import metrics  # noqa: E402

OUT = ROOT / "context/experiments/response-vs-lims-2026-09-15.json"


def main():
    started = time.time()
    old = pd.read_csv(ROOT / "artifacts/predictions.csv", parse_dates=["decision_time", "target_time"])
    signals, lab, online = load_sources(ROOT / "task")
    frame = rm.prepare(signals, online)
    grid = frame.index[frame.index.minute % 30 == 0]
    grid = grid[(grid >= grid[0] + pd.Timedelta("31d")) & (grid <= grid[-1] - pd.Timedelta("4h"))]
    decision_rows = rm.rows(frame, grid)
    print(f"подготовка {time.time() - started:.0f} с")

    samples = old.target_time
    months = sorted({pd.Timestamp(t.year, t.month, 1) for t in pd.concat([samples - pd.Timedelta("3h"),
                                                                           samples - pd.Timedelta("2h")])})
    artifacts = {}
    for tau in months:
        artifacts[tau] = rm.fit(frame, decision_rows, tau, boot=0)
        print(f"артефакт {tau.date()}: w={artifacts[tau].w} r0={artifacts[tau].r0:.3f} ({time.time() - started:.0f} с)")

    def response(when):
        when = pd.Timestamp(when)
        art = artifacts[pd.Timestamp(when.year, when.month, 1)]
        state = rm.live_state(frame, when)
        answer = rm.predict(art, state, 0.0)
        if answer["zone"] != "HOLD":
            return np.nan, np.nan, np.nan, answer["zone"], state
        return answer["baseline"], answer["lower"], answer["upper"], "HOLD", state

    table = {name: [] for name in ("resp2", "resp2_lo", "resp2_hi", "resp3", "resp3_lo", "resp3_hi",
                                   "pak24h_2", "pak30m_2", "zone2", "zone3")}
    for sample in samples:
        for horizon in (2, 3):
            value, lower, upper, zone, state = response(sample - pd.Timedelta(hours=horizon))
            table[f"resp{horizon}"].append(value)
            table[f"resp{horizon}_lo"].append(lower)
            table[f"resp{horizon}_hi"].append(upper)
            table[f"zone{horizon}"].append(zone)
            if horizon == 2:
                ok = np.isfinite(state["PAK24h"]) and state["PAK24h_cov"] >= 0.5
                table["pak24h_2"].append(state["PAK24h"] if ok else np.nan)
                table["pak30m_2"].append(state["PAK30m"] if np.isfinite(state["PAK30m"]) else np.nan)
    for name, values in table.items():
        old[name] = values

    y = old.actual_sulfur.to_numpy(float)
    variants = {
        "last_pak (выбрана)": ("last_pak", "lower", "upper"),
        "catboost_no_pak (запасная)": ("catboost_no_pak", "fallback_lower", "fallback_upper"),
        "catboost": ("catboost", None, None),
        "last_lab": ("last_lab", None, None),
        "ridge": ("ridge", None, None),
        "отклик, горизонт 2 ч": ("resp2", "resp2_lo", "resp2_hi"),
        "отклик, горизонт 3 ч": ("resp3", "resp3_lo", "resp3_hi"),
        "ПАК24h, 2 ч": ("pak24h_2", None, None),
        "ПАК30m, 2 ч": ("pak30m_2", None, None),
    }
    common = np.ones(len(old), bool)
    for column, _, _ in variants.values():
        common &= np.isfinite(old[column].to_numpy(float))

    def score(mask):
        out = {}
        for label, (column, lo, hi) in variants.items():
            pred = old[column].to_numpy(float)[mask]
            lower = old[lo].to_numpy(float)[mask] if lo else None
            upper = old[hi].to_numpy(float)[mask] if hi else None
            m = metrics(y[mask], pred, 10.0, lower, upper, near_margin=5.0)
            m["bias"] = float(np.nanmean(pred - y[mask])) if np.isfinite(pred).any() else None
            out[label] = m
        return out

    full = np.ones(len(old), bool)
    result = {
        "samples": int(len(old)), "common": int(common.sum()),
        "exceedances_common": int((y[common] > 10).sum()),
        "zones_h2": pd.Series(table["zone2"]).value_counts().to_dict(),
        "zones_h3": pd.Series(table["zone3"]).value_counts().to_dict(),
        "artifacts": {str(t.date()): {"w": a.w, "r0": a.r0, "beta": a.beta} for t, a in artifacts.items()},
        "common_rows": score(common),
        "own_availability": score(full),
        "seconds": round(time.time() - started, 1),
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1, default=float))
    print(f"общих проб {result['common']} из {result['samples']}, превышений {result['exceedances_common']}")
    head = f"{'вариант':28} {'MAE':>6} {'RMSE':>6} {'bias':>6} {'recall':>6} {'ЛТ':>5} {'покр':>5} {'шир':>5} {'UB rec':>6} {'UB ЛТ':>6}"
    print(head)
    for label, m in result["common_rows"].items():
        f = lambda k, d=2: "—" if m.get(k) is None else f"{m[k]:.{d}f}"
        print(f"{label:28} {f('mae')} {f('rmse')} {f('bias')} {f('recall')} {f('false_alarm_rate')} "
              f"{f('interval_coverage')} {f('mean_interval_width', 1)} {f('upper_bound_recall')} {f('upper_bound_false_alarm_rate')}")
    print("доступность:", {k: round(v["availability"], 3) for k, v in result["own_availability"].items()})


if __name__ == "__main__":
    main()
