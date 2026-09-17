"""T110 (а): смещение ПАК–ЛИМС в одно время отбора.

Пара: проба ЛИМС (время отбора) и последнее показание ПАК не позже отбора с допуском 30 мин —
то же правило, что `pak_at_lab` в build_features. Показание ПАК внутри плоского участка из
`pak_frozen_readings` одинаковых значений, известного к моменту отбора, не доверенное.
Разность d = ЛИМС − ПАК (положительная: ПАК занижает).

Запуск из корня основного репозитория (task/ и artifacts/ не коммитятся):
  AGENTIC_DECISION_ENABLED=0 PYTHONPATH=src .venv/bin/python context/response-research/tank/b1_bias.py
Вывод: context/response-research/tank/out/b1_bias.json, b1_pairs.csv и печать таблиц.
"""
import json
import os
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(os.environ.get("NEFTECODE_ROOT", "."))
HERE = Path(__file__).resolve().parent / "out"  # сырые пары и таблицы не коммитятся (../.gitignore)
sys.path.insert(0, str(ROOT / "src"))
from neftecode.infrastructure.data.data import load_sources  # noqa: E402

bundle = pickle.load((ROOT / "artifacts/model.pkl").open("rb"))
cfg = bundle["config"]
FROZEN = int(cfg.get("pak_frozen_readings", 4))
CONFLICT = float(cfg.get("pak_conflict_mgkg", 4.749))
PERIODS = [("train", None, cfg["train_end"]), ("validation", cfg["train_end"], cfg["validation_end"]),
           ("calibration", cfg["validation_end"], cfg["calibration_end"]), ("test_2026", cfg["calibration_end"], None)]


def causal_frozen(p: pd.Series) -> pd.Series:
    """Показание в плоском участке длиной ≥ FROZEN, считая только прошлые показания (причинно)."""
    changed = p.diff().abs().gt(1e-6) | p.diff().isna()
    run = changed.cumsum()
    length = p.groupby(run).cumcount() + 1
    return length >= FROZEN


def pairs() -> pd.DataFrame:
    _, lab, online = load_sources(ROOT / "task", cfg["train_end"])
    p = online.set_index("time").value.sort_index()
    p = p[~p.index.duplicated(keep="last")]
    frozen = causal_frozen(p)
    trusted = p[~frozen]
    lab = lab.dropna(subset=["value"]).sort_values("time")
    idx = pd.DatetimeIndex(lab.time)
    tol = pd.Timedelta(minutes=30)
    raw = p.reindex(idx, method="ffill", tolerance=tol).to_numpy()
    good = trusted.reindex(idx, method="ffill", tolerance=tol).to_numpy()
    out = pd.DataFrame({"time": lab.time.to_numpy(), "lims": lab.value.to_numpy(), "pak_raw": raw, "pak": good})
    out["d"] = out.lims - out.pak
    out["conflict"] = (out.d.abs() > CONFLICT)
    out["period"] = "?"
    for name, a, b in PERIODS:
        m = pd.Series(True, index=out.index)
        if a: m &= out.time >= pd.Timestamp(a)
        if b: m &= out.time < pd.Timestamp(b)
        out.loc[m, "period"] = name
    return out


def stats(d: pd.Series, n_boot=2000, seed=42) -> dict:
    d = d.dropna().to_numpy()
    if len(d) < 3:
        return {"n": int(len(d))}
    rng = np.random.default_rng(seed)
    boot = rng.choice(d, (n_boot, len(d)))
    means, medians = boot.mean(1), np.median(boot, 1)
    return {"n": int(len(d)), "mean": round(float(d.mean()), 3),
            "mean_ci": [round(float(x), 3) for x in np.quantile(means, [.025, .975])],
            "median": round(float(np.median(d)), 3),
            "median_ci": [round(float(x), 3) for x in np.quantile(medians, [.025, .975])],
            "sd": round(float(d.std(ddof=1)), 3), "mae": round(float(np.abs(d).mean()), 3),
            "share_pak_below": round(float((d > 0).mean()), 3),
            "q10_q90": [round(float(x), 3) for x in np.quantile(d, [.1, .9])]}


def fit_line(frame: pd.DataFrame) -> dict:
    """ЛИМС = a + b·ПАК методом наименьших квадратов (условное среднее ЛИМС при известном ПАК)."""
    x, y = frame.pak.to_numpy(), frame.lims.to_numpy()
    b, a = np.polyfit(x, y, 1)
    return {"a": round(float(a), 4), "b": round(float(b), 4), "n": int(len(x)),
            "corr": round(float(np.corrcoef(x, y)[0, 1]), 3)}


def main():
    df = pairs()
    ok = df.pak.notna()
    clean = ok & ~df.conflict
    res = {"rule": {"pak_tolerance_min": 30, "pak_frozen_readings": FROZEN, "conflict_mgkg": CONFLICT,
                    "periods": PERIODS, "d": "ЛИМС − ПАК в момент отбора"},
           "coverage": {p: {"lims": int((df.period == p).sum()), "paired": int(((df.period == p) & ok).sum()),
                            "conflict": int(((df.period == p) & ok & df.conflict).sum())} for p, *_ in PERIODS},
           "by_period": {}, "by_period_no_conflict": {}, "by_half_year": {}, "by_level_pak": {},
           "by_level_lims": {}, "rolling": {}, "line": {}}
    for p, *_ in PERIODS:
        res["by_period"][p] = stats(df.loc[ok & (df.period == p), "d"])
        res["by_period_no_conflict"][p] = stats(df.loc[clean & (df.period == p), "d"])
    half = df.time.dt.year.astype(str) + np.where(df.time.dt.month <= 6, "H1", "H2")
    for h in sorted(half.unique()):
        res["by_half_year"][h] = stats(df.loc[clean & (half == h), "d"])
    # Уровень: бины по ПАК (известен в момент решения) и по ЛИМС (для сравнения; даёт регрессию к среднему).
    bins = [0, 4, 6, 8, 10, 100]
    for col, key in [("pak", "by_level_pak"), ("lims", "by_level_lims")]:
        cut = pd.cut(df[col], bins, right=False)
        for per in ["train", "test_2026"]:
            for b in cut.cat.categories:
                m = clean & (df.period == per) & (cut == b)
                res[key][f"{per} {b}"] = stats(df.loc[m, "d"], n_boot=500)
    # Линейная связь ЛИМС от ПАК по периодам (без конфликтов).
    for p, *_ in PERIODS:
        res["line"][p] = fit_line(df[clean & (df.period == p)])
    # Причинная скользящая медиана последних 20 пар (пара известна через 4 ч после отбора):
    # только как показатель стабильности, не как кандидат прогноза (кандидаты — T105).
    c = df[clean].reset_index(drop=True)
    roll = c.d.rolling(20, min_periods=20).median()
    c["roll20"] = roll
    sign = np.sign(roll.dropna())
    res["rolling"] = {
        "n20_sign_changes": int((sign.diff().fillna(0) != 0).sum()),
        "share_positive": round(float((roll.dropna() > 0).mean()), 3),
        "by_half_year": {h: {"min": round(float(g.min()), 3), "median": round(float(g.median()), 3),
                              "max": round(float(g.max()), 3)}
                         for h, g in c.assign(h=half[clean].to_numpy()).dropna(subset=["roll20"]).groupby("h").roll20},
    }
    # Дрейф: наклон d по времени (мг/кг в год) до 2026 и Спирмен d с ПАК в train.
    pre = c[c.time < pd.Timestamp(cfg["calibration_end"])]
    years = (pre.time - pre.time.min()).dt.total_seconds() / (365.25 * 86400)
    res["trend_pre2026_mgkg_per_year"] = round(float(np.polyfit(years, pre.d, 1)[0]), 3)
    tr = c[c.period == "train"]
    res["train_spearman_d_vs_pak"] = round(float(tr.d.corr(tr.pak, method="spearman")), 3)
    te = c[c.period == "test_2026"]
    res["test_spearman_d_vs_pak"] = round(float(te.d.corr(te.pak, method="spearman")), 3)
    df.to_csv(HERE / "b1_pairs.csv", index=False)
    (HERE / "b1_bias.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    HERE.mkdir(exist_ok=True)
    main()
