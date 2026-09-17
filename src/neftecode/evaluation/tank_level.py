"""Частичная проверка оценки серы резервуара (T89).

Эталона серы товарной смеси в пакете нет. Единственный доступный ориентир — проба ЛИМС ГО точки 2 в
момент отбора: при рецепте 100 % основного компонента смесь равна содержимому резервуара, а содержимое
оценивается как среднее доверенных показаний ПАК за окно обновления. Сравнение диагностическое:
проба описывает поток в момент отбора, оценка — среднее за окно, поэтому расхождение растёт с окном.
"""
import numpy as np
import pandas as pd

from neftecode.infrastructure.data.data import recent_quality_history
from neftecode.infrastructure.live.advisor import LiveError, estimate_tank_sulfur


def tank_level_check(lab: pd.DataFrame, online: pd.DataFrame, cfg: dict, windows_hours=(6.0, 19.0, 42.0, 72.0),
                     start="2026-01-01", min_coverage: float = 0.5) -> dict:
    samples = lab[lab.time >= pd.Timestamp(start)]
    rows = []
    for when, actual in zip(samples.time, samples.value):
        state = {"decision_time": when.isoformat(), **recent_quality_history(lab, online, when, cfg)}
        row = {"sample_time": when.isoformat(), "lab": float(actual),
               "last_pak": state.get("pak_last_trusted_value")}
        for window in windows_hours:
            raw = {"policy": {"tank_level_window_hours": float(window), "tank_level_min_coverage": min_coverage}}
            try:
                row[f"w{window:g}"] = float(estimate_tank_sulfur(raw, state)["value"])
            except LiveError:
                row[f"w{window:g}"] = None
        rows.append(row)
    frame = pd.DataFrame(rows)
    summary = {}
    for column in ["last_pak", *[f"w{w:g}" for w in windows_hours]]:
        good = frame[column].notna() & frame["lab"].notna()
        errors = frame.loc[good, column] - frame.loc[good, "lab"]
        summary[column] = {"n": int(good.sum()),
                           "mae": round(float(errors.abs().mean()), 3) if good.any() else None,
                           "bias": round(float(errors.mean()), 3) if good.any() else None,
                           "corr": round(float(np.corrcoef(frame.loc[good, column], frame.loc[good, "lab"])[0, 1]), 3)
                           if good.sum() > 2 else None}
    return {"since": start, "samples": int(len(frame)), "windows_hours": list(windows_hours),
            "min_coverage": min_coverage, "summary": summary,
            "scope": ("Проверка оценки содержимого резервуара по пробе ЛИМС ГО точки 2 в момент отбора "
                      "(случай рецепта 100 % main). Не проверка смешения: измерений товарной смеси нет. "
                      "Проба описывает поток в момент отбора, оценка — среднее за окно.")}
