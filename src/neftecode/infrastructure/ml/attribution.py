"""Which part of the chain carries the risk: crude/AVT side, hydrotreater, or the analysers.

The brief frames diesel as a coupled chain, so a number that only describes 24-2000
answers half the question. Attribution here is grouped and model-based: it says what
the model leans on, which is weaker than saying what the plant does.
"""
import numpy as np
import pandas as pd

GROUPS = {
    "avt": "АВТ и сырье",
    "ht": "Гидроочистка 24-2000",
    "lab": "Лабораторный анализ",
    "pak": "Поточный анализатор",
}


def group_columns(columns) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {key: [] for key in GROUPS}
    for column in columns:
        key = column.split(".", 1)[0]
        grouped.setdefault(key, []).append(column)
    return {key: cols for key, cols in grouped.items() if cols}


def grouped_permutation_importance(predict, x: pd.DataFrame, y, repeats: int = 5,
                                   seed: int = 42) -> dict:
    """Mean absolute error increase when a whole group of columns is shuffled together."""
    y = np.asarray(y, float)
    base = predict(x)
    good = np.isfinite(base) & np.isfinite(y)
    if good.sum() < 30:
        raise ValueError("Недостаточно наблюдений с прогнозом для оценки вклада групп")
    baseline = float(np.abs(y[good] - base[good]).mean())
    rng = np.random.default_rng(seed)
    result = {}
    for key, columns in group_columns(x.columns).items():
        scores = []
        for _ in range(repeats):
            shuffled = x.copy()
            order = rng.permutation(len(shuffled))
            shuffled[columns] = shuffled[columns].to_numpy()[order]
            prediction = predict(shuffled)
            fine = np.isfinite(prediction) & np.isfinite(y)
            scores.append(float(np.abs(y[fine] - prediction[fine]).mean()))
        result[key] = {"label": GROUPS.get(key, key), "columns": len(columns),
                       "mae_when_shuffled": float(np.mean(scores)),
                       "increase": float(np.mean(scores) - baseline)}
    total = sum(max(0.0, r["increase"]) for r in result.values())
    for record in result.values():
        record["share"] = float(max(0.0, record["increase"]) / total) if total > 0 else None
    return {"baseline_mae": baseline, "repeats": repeats, "groups": result,
            "scope": "Вклад в точность модели, а не измеренный вклад участка в качество продукта. "
                     "Сильно связанные признаки делят вклад между собой."}


def attribute_decision(predict, x_row: pd.DataFrame, reference: pd.Series) -> dict:
    """How the prediction moves when one group is replaced by a typical historical state."""
    if len(x_row) != 1:
        raise ValueError("Разбор вклада выполняется для одного момента решения")
    base = float(predict(x_row)[0])
    if not np.isfinite(base):
        return {"available": False, "reason": "На этот момент прогноз недоступен"}
    contributions = {}
    for key, columns in group_columns(x_row.columns).items():
        typical = x_row.copy()
        typical[columns] = reference[columns].to_numpy()
        value = float(predict(typical)[0])
        if not np.isfinite(value):
            continue
        contributions[key] = {"label": GROUPS.get(key, key),
                              "prediction_if_typical": value, "effect": base - value}
    ranked = sorted(contributions.items(), key=lambda kv: -abs(kv[1]["effect"]))
    return {
        "available": True, "prediction": base,
        "groups": dict(contributions),
        "leading_group": ranked[0][0] if ranked else None,
        "leading_label": GROUPS.get(ranked[0][0], ranked[0][0]) if ranked else None,
        "reason": (f"Наибольший вклад в текущую оценку дает группа «{GROUPS.get(ranked[0][0], ranked[0][0])}»: "
                   f"при типичном состоянии этой группы прогноз был бы "
                   f"{ranked[0][1]['prediction_if_typical']:.2f} вместо {base:.2f} мг/кг") if ranked else "",
        "scope": "Замена группы признаков на медиану обучающего периода. Это разбор поведения модели, "
                 "а не измеренный вклад установки; сочетание признаков при подстановке может быть нереальным.",
    }
