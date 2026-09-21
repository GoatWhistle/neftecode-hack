"""Find frozen-snapshot moments (>= 2026-01-01) from the data with the production trust rules. Output config/snapshot_moments.json.

Uses build_features (src, read-only) with the trained bundle's config (lab_max_age 48 h, pak_max_age 30 min,
pak_frozen_readings 4, pak_conflict 4.749 mg/kg) on the 10-min grid.
"""
import pickle
from tcommon import *
from neftecode.infrastructure.data.data import build_features

s, lab, on, ex = load()
bundle = pickle.load((ROOT / "artifacts/model.pkl").open("rb"))
cfg = bundle["config"]
times = s.index[s.index >= "2026-01-01"]
x, meta = build_features(s, lab, on, times, cfg)
meta = meta.set_index("decision_time")
meta["T6"] = s["ht.T6"].reindex(times).to_numpy()
meta["T6_nan"] = meta.T6.isna()
res = {}


def first(mask, label):
    idx = meta.index[mask.to_numpy()]
    return None if len(idx) == 0 else idx[0]


def row(t):
    if t is None:
        return None
    r = meta.loc[t]
    return {k: (r[k].isoformat() if isinstance(r[k], pd.Timestamp) else (None if pd.isna(r[k]) else (r[k].item() if hasattr(r[k], "item") else r[k])))
            for k in ["lab_sample_time", "lab_value", "lab_age_hours", "lab_usable", "pak_sample_time", "pak_value", "pak_age_minutes",
                      "pak_frozen", "pak_conflict", "pak_usable", "telemetry_missing_fraction", "T6"]}


moments = []
t = pd.Timestamp("2026-01-05 08:00"); moments.append(("norm", t, row(t)))
t = pd.Timestamp("2026-01-09 01:10"); moments.append(("frozen_pak", t, row(t)))
# lab older than 48 h: first moment in 2026 where lab_age_hours > 48 (and PAK usable, so the case is isolated)
m = (meta.lab_age_hours > 48) & meta.pak_usable
t = first(m, "lab_stale"); moments.append(("lab_stale", t, row(t)))
res["lab_stale_episodes"] = int(((meta.lab_age_hours > 48) & ~(meta.lab_age_hours.shift(1) > 48)).sum())
# conflict PAK vs LIMS
m = meta.pak_conflict & meta.lab_usable
t = first(m, "conflict"); moments.append(("conflict", t, row(t)))
res["conflict_rows"] = int(m.sum()); res["conflict_first_days"] = sorted({str(d) for d in meta.index[m.to_numpy()].date})[:10]
# T6 NaN with live PAK
m = meta.T6_nan & meta.pak_usable
t = first(m, "t6_nan"); moments.append(("t6_nan", t, row(t)))
res["t6_nan_rows_2026"] = int(meta.T6_nan.sum()); res["t6_nan_with_pak_rows"] = int(m.sum())
res["t6_nan_days"] = sorted({str(d) for d in meta.index[meta.T6_nan.to_numpy()].date})
res["t6_nan_rows_all_history"] = int(s["ht.T6"].isna().sum())
res["grid_gaps_over_10min"] = int((s.index.to_series().diff() > pd.Timedelta("10min")).sum())
# substitute: any core control tag missing (F9 stub -> NaN) with live PAK and T6 present
core = ["ht.F9", "ht.T5", "ht.P13", "ht.F2", "ht.T11"]
core_nan = s[core].reindex(times).isna()
meta["core_nan_tags"] = [",".join(c for c, v in zip(core, r) if v) for r in core_nan.to_numpy()]
m = core_nan.any(axis=1).to_numpy() & meta.pak_usable.to_numpy() & ~meta.T6_nan.to_numpy()
t = first(pd.Series(m, index=meta.index), "core_nan"); moments.append(("telemetry_nan_substitute", t, row(t)))
res["core_nan_with_pak_rows"] = int(m.sum()); res["core_nan_first_tags"] = None if t is None else meta.loc[t, "core_nan_tags"]
res["core_nan_days"] = sorted({str(d) for d in meta.index[m].date})[:12]
# refusal: no usable lab and no usable PAK
m = ~meta.lab_usable & ~meta.pak_usable
t = first(m, "refusal"); moments.append(("refusal", t, row(t)))
res["refusal_rows"] = int(m.sum()); res["refusal_days"] = sorted({str(d) for d in meta.index[m.to_numpy()].date})[:15]
# frozen check: PAK raw values around 2026-01-09 01:10
p = on.set_index("time").value
res["frozen_check_2026-01-09"] = {str(k): float(v) for k, v in p["2026-01-09 00:00":"2026-01-09 03:00"].items()}
res["moments"] = {name: (None if r is None else {"at": str(t), **r}) for name, t, r in moments}
dump("snapshot_moments.json", res)
print(json.dumps(res, indent=1, ensure_ascii=False, default=str))
