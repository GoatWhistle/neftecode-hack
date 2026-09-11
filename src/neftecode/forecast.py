"""Frozen chronological experiment. Final test never selects or calibrates models."""
import math

import numpy as np
from catboost import CatBoostRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .data import split_periods


def metrics(y, prediction, limit=10, lower=None, upper=None):
    y, prediction = np.asarray(y), np.asarray(prediction)
    valid = np.isfinite(prediction)
    result = {"n": len(y), "predicted": int(valid.sum()), "availability": float(valid.mean())}
    if not valid.any():
        return result
    yy, pp = y[valid], prediction[valid]
    risk = yy > limit
    alarm = pp > limit
    near = (yy >= 5) & (yy <= 15)
    result.update(
        mae=float(np.abs(yy - pp).mean()), rmse=float(np.sqrt(np.mean((yy - pp) ** 2))),
        mae_near_limit=float(np.abs(yy[near] - pp[near]).mean()) if near.any() else None,
        actual_exceedances=int(risk.sum()),
        recall=float(alarm[risk].mean()) if risk.any() else None,
        false_alarm_rate=float(alarm[~risk].mean()) if (~risk).any() else None,
    )
    if lower is not None:
        lo, hi = np.asarray(lower)[valid], np.asarray(upper)[valid]
        result.update(
            interval_coverage=float(((yy >= lo) & (yy <= hi)).mean()),
            mean_interval_width=float(np.mean(hi - lo)),
            upper_bound_recall=float((hi[risk] > limit).mean()) if risk.any() else None,
            upper_bound_false_alarm_rate=float((hi[~risk] > limit).mean()) if (~risk).any() else None,
            below_limit_fraction=float((hi <= limit).mean()),
            missed_exceedances=int(((hi <= limit) & risk).sum()),
        )
    return result


def calibrate(y, prediction, coverage):
    if not 0 < coverage < 1:
        raise ValueError("Целевое покрытие должно быть между 0 и 1")
    good = np.isfinite(prediction)
    residuals = np.abs(np.log1p(np.asarray(y)[good]) - np.log1p(np.asarray(prediction)[good]))
    if len(residuals) < 30:
        raise ValueError("Недостаточно независимых анализов для калибровки диапазона")
    rank = min(math.ceil((len(residuals) + 1) * coverage), len(residuals))
    return float(np.sort(residuals)[rank - 1])


def interval(prediction, radius):
    center = np.log1p(prediction)
    return np.maximum(0, np.expm1(center - radius)), np.expm1(center + radius)


def predict_candidate(bundle, name, x):
    if name == "last_lab":
        return x["lab.sulfur"].to_numpy()
    if name == "last_pak":
        return x["pak.sulfur"].to_numpy()
    model = bundle["models"][name]
    columns = bundle["columns"][name]
    return np.maximum(0, np.expm1(model.predict(x[columns])))


def run_experiment(x, meta, cfg):
    masks = split_periods(meta, cfg)
    if any(mask.sum() < 30 for mask in masks.values()):
        raise ValueError("Меньше 30 лабораторных анализов в одном из временных периодов")
    train, val, cal, test = [masks[k] for k in ("train", "validation", "calibration", "test")]
    y = meta.actual_sulfur.to_numpy()
    columns = x.columns[x.loc[train].nunique() > 1].tolist()
    no_pak = [c for c in columns if not c.startswith("pak.")]
    bundle = {"models": {}, "columns": {}, "radii": {}, "config": cfg}
    candidates = ["last_lab", "last_pak", "ridge", "catboost", "catboost_no_pak"]
    predictions = {}
    for name in candidates:
        if name not in ("last_lab", "last_pak"):
            cols = no_pak if name.endswith("no_pak") else columns
            if name == "ridge":
                model = make_pipeline(SimpleImputer(strategy="median", add_indicator=True),
                                      StandardScaler(), Ridge(alpha=100))
            else:
                model = CatBoostRegressor(iterations=300, depth=4, learning_rate=.035,
                                          loss_function="MAE", random_seed=cfg["seed"],
                                          thread_count=2, verbose=False, allow_writing_files=False)
            model.fit(x.loc[train, cols], np.log1p(y[train]))
            bundle["models"][name] = model
            bundle["columns"][name] = cols
        predictions[name] = predict_candidate(bundle, name, x)
    # Selection on the same validation observations, including both simple baselines.
    common = val.copy()
    for p in predictions.values():
        common &= np.isfinite(p)
    if common.sum() < 30:
        raise ValueError("Недостаточно общих наблюдений для честного сравнения моделей")
    scores = {name: float(np.abs(y[common] - p[common]).mean()) for name, p in predictions.items()}
    selected = min(scores, key=scores.get)
    bundle["selected"] = selected
    # Fallback is evaluated separately; never claim it retains the main model's accuracy.
    bundle["fallback"] = "catboost_no_pak"
    # Typical training state, used later to attribute a single decision to a chain group.
    bundle["reference_row"] = x.loc[train].median()
    common_test = test.copy()
    for prediction in predictions.values():
        common_test &= np.isfinite(prediction)
    results = {}
    for name, prediction in predictions.items():
        radius = calibrate(y[cal], prediction[cal], cfg["interval_coverage"])
        bundle["radii"][name] = radius
        lo, hi = interval(prediction, radius)
        results[name] = {
            "validation_common_mae": scores[name],
            "validation": metrics(y[val], prediction[val]),
            "test": metrics(y[test], prediction[test], cfg["sulfur_limit"], lo[test], hi[test]),
            "test_common": metrics(y[common_test], prediction[common_test], cfg["sulfur_limit"], lo[common_test], hi[common_test]),
        }
    output = meta.loc[test].copy().reset_index(drop=True)
    for name, prediction in predictions.items():
        output[name] = prediction[test]
    main = predictions[selected][test]
    lo, hi = interval(main, bundle["radii"][selected])
    output["prediction"], output["lower"], output["upper"] = main, lo, hi
    fallback = predictions[bundle["fallback"]][test]
    flo, fhi = interval(fallback, bundle["radii"][bundle["fallback"]])
    output["fallback_prediction"], output["fallback_lower"], output["fallback_upper"] = fallback, flo, fhi
    summary = {
        "selected": selected, "selection": "MAE на общем наборе validation; тест не участвует",
        "validation_common_n": int(common.sum()),
        "test_common_n": int(common_test.sum()),
        "periods": {name: {"n": int(m.sum()), "first_decision": str(meta.loc[m, "decision_time"].min()),
                           "last_target": str(meta.loc[m, "target_time"].max())} for name, m in masks.items()},
        "excluded_boundary_rows": int((~np.logical_or.reduce(list(masks.values()))).sum()),
        "models": results, "assumptions": cfg["assumptions"],
        "scope": "Прогноз за 2 часа до времени реальной пробы. Один анализ — одна целевая строка. Не эффект управления.",
    }
    return bundle, summary, output
