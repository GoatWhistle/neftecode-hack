"""T110 (б): варианты учёта смещения ПАК–ЛИМС, параметры — только из данных до проверяемого периода.

Проверка на парах «ЛИМС — ПАК в момент отбора» (b1_pairs.csv) и на оценке серы резервуара
(`tank_level_check`, окно 19 ч, как в artifacts/tank_level_check.json).

Варианты поправки точки:
  V0  без поправки;
  V1a константа = медиана d на train (< 2025-01-01);
  V1b константа = медиана d за последние 6 месяцев перед периодом (для 2026 — 2025 H2);
  V1c линия ЛИМС = a + b·ПАК, подогнанная на train.
Скользящая медиана последних N пар — кандидат F2 протокола T103; на 2026 она здесь НЕ считается
(2026 для неё открывается только в T108). Для неё — только складки 2023 H2 – 2025 H2.

V2 не меняет точку: неопределённость смещения u = квантиль 0.9 |скользящей медианы 20 пар| до 2026.

Запуск из корня основного репозитория:
  AGENTIC_DECISION_ENABLED=0 PYTHONPATH=src .venv/bin/python context/response-research/tank/b2_variants.py
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
from neftecode.infrastructure.live.tank_check import tank_level_check  # noqa: E402

bundle = pickle.load((ROOT / "artifacts/model.pkl").open("rb"))
cfg = bundle["config"]
LAB_DELAY = pd.Timedelta(hours=float(cfg.get("lab_delay_hours", 4)))
df = pd.read_csv(HERE / "b1_pairs.csv", parse_dates=["time"])
clean = df[df.pak.notna() & ~df.conflict].reset_index(drop=True)
TEST = pd.Timestamp(cfg["calibration_end"])
train = clean[clean.time < pd.Timestamp(cfg["train_end"])]


def score(y, x) -> dict:
    e = np.asarray(x) - np.asarray(y)
    return {"n": int(len(e)), "mae": round(float(np.abs(e).mean()), 3), "bias_est_minus_lims": round(float(e.mean()), 3)}


def last6(before: pd.Timestamp) -> float:
    part = clean[(clean.time >= before - pd.DateOffset(months=6)) & (clean.time + LAB_DELAY <= before)]
    return float(part.d.median())


V1A = float(train.d.median())
b, a = np.polyfit(train.pak, train.lims, 1)
out = {"params": {"V1a_offset": round(V1A, 3), "V1c_line": {"a": round(float(a), 3), "b": round(float(b), 3)}}}

# Пары: validation, calibration, 2026.
periods = {"validation": (cfg["train_end"], cfg["validation_end"]),
           "calibration": (cfg["validation_end"], cfg["calibration_end"]),
           "test_2026": (cfg["calibration_end"], None)}
out["pairs"] = {}
for name, (s, e) in periods.items():
    s = pd.Timestamp(s)
    m = clean.time >= s
    if e:
        m &= clean.time < pd.Timestamp(e)
    part = clean[m]
    v1b = last6(s)
    out["pairs"][name] = {"V1b_offset": round(v1b, 3),
                          "V0": score(part.lims, part.pak),
                          "V1a": score(part.lims, part.pak + V1A),
                          "V1b": score(part.lims, part.pak + v1b),
                          "V1c": score(part.lims, a + b * part.pak)}

# Скользящая медиана N пар (причинно: пара известна через LAB_DELAY) — только до 2026.
def rolling_offset(n: int) -> np.ndarray:
    avail = (clean.time + LAB_DELAY).to_numpy()
    times = clean.time.to_numpy()
    d = clean.d.to_numpy()
    res = np.zeros(len(clean))
    for i, t in enumerate(times):
        known = d[avail <= t]  # проба i сама недоступна в момент своего отбора
        res[i] = np.median(known[-n:]) if len(known) >= 5 else 0.0
    return res

folds = [("2023H2", "2023-07-01", "2024-01-01"), ("2024H1", "2024-01-01", "2024-07-01"),
         ("2024H2", "2024-07-01", "2025-01-01"), ("2025H1", "2025-01-01", "2025-07-01"),
         ("2025H2", "2025-07-01", "2026-01-01")]
out["rolling_pre2026"] = {}
for n in (10, 20, 40):
    off = rolling_offset(n)
    rows = {}
    for f, s, e in folds:
        m = ((clean.time >= s) & (clean.time < e)).to_numpy()
        rows[f] = {"V0": score(clean.lims[m], clean.pak[m]), f"R{n}": score(clean.lims[m], clean.pak[m] + off[m])}
    out["rolling_pre2026"][f"N{n}"] = {
        "folds": rows,
        "mean_mae_V0": round(float(np.mean([r["V0"]["mae"] for r in rows.values()])), 3),
        "mean_mae_R": round(float(np.mean([r[f"R{n}"]["mae"] for r in rows.values()])), 3),
        "mean_abs_bias_V0": round(float(np.mean([abs(r["V0"]["bias_est_minus_lims"]) for r in rows.values()])), 3),
        "mean_abs_bias_R": round(float(np.mean([abs(r[f"R{n}"]["bias_est_minus_lims"]) for r in rows.values()])), 3)}
off20 = rolling_offset(20)
pre = (clean.time < TEST).to_numpy() & (np.arange(len(clean)) >= 20)
u = float(np.quantile(np.abs(off20[pre]), 0.9))
out["V2_uncertainty_u_mgkg"] = {"q90_abs_roll20_pre2026": round(u, 3),
                                "q50": round(float(np.quantile(np.abs(off20[pre]), 0.5)), 3),
                                "halfyear_median_range_pre2026": [-0.968, 1.035]}

# Оценка резервуара (окно 19 ч): поправки V1a/V1b на 2026; проверка против пробы ЛИМС в момент отбора.
_, lab, online = load_sources(ROOT / "task", cfg["train_end"])
check = tank_level_check(lab, online, cfg, windows_hours=(19.0,))
print("tank_check summary (сверка с артефактом):", check["summary"])
# Строки заново: summary не хранит строки, повторяем расчёт через ту же функцию с возвратом строк.
from neftecode.infrastructure.data.data import recent_quality_history  # noqa: E402
from neftecode.infrastructure.live.advisor import LiveError, estimate_tank_sulfur  # noqa: E402
rows = []
for when, y in zip(lab.time[lab.time >= TEST], lab.value[lab.time >= TEST]):
    state = {"decision_time": when.isoformat(), **recent_quality_history(lab, online, when, cfg)}
    try:
        lvl = estimate_tank_sulfur({"policy": {"tank_level_window_hours": 19.0, "tank_level_min_coverage": 0.5}}, state)
        rows.append((when, y, lvl["value"], lvl["source"]))
    except LiveError:
        pass
tank = pd.DataFrame(rows, columns=["time", "lims", "tank", "source"]).dropna()
v1b = last6(TEST)
pakbased = tank.source == "pak"
out["tank_2026_w19"] = {
    "n": int(len(tank)), "n_pak_based": int(pakbased.sum()),
    "V0": score(tank.lims, tank.tank),
    "V1a": score(tank.lims, np.where(pakbased, tank.tank + V1A, tank.tank)),
    "V1b": score(tank.lims, np.where(pakbased, tank.tank + v1b, tank.tank)),
    "V1c": score(tank.lims, np.where(pakbased, a + b * tank.tank, tank.tank)),
    "corr_V0": round(float(np.corrcoef(tank.lims, tank.tank)[0, 1]), 3),
    "note": "Проба ЛИМС описывает поток в момент отбора, а не содержимое резервуара: MAE здесь меряет не то."}
(HERE / "b2_variants.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
print(json.dumps(out, ensure_ascii=False, indent=1))
