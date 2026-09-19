import math

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from neftecode.infrastructure.data.data import split_periods, validate_forecast_selection


_UNSET = object()


def metrics(y, prediction, limit=10, lower=None, upper=None, *,
            direction="max", near_margin=5.0):
    if direction not in {"max", "min"}:
        raise ValueError("Направление ограничения должно быть max или min")
    if limit is not None and not np.isfinite(limit):
        raise ValueError("Предел должен быть конечным или None")
    if near_margin is not None and (not np.isfinite(near_margin) or near_margin < 0):
        raise ValueError("Окрестность предела должна быть конечной и неотрицательной")
    risk_configured = limit is not None and limit is not _UNSET
    y, prediction = np.asarray(y), np.asarray(prediction)
    valid = np.isfinite(prediction)
    result = {"n": len(y), "predicted": int(valid.sum()), "availability": float(valid.mean())}
    if not valid.any():
        return result
    yy, pp = y[valid], prediction[valid]
    result.update(
        mae=float(np.abs(yy - pp).mean()), rmse=float(np.sqrt(np.mean((yy - pp) ** 2))),
    )
    if risk_configured:
        risk = yy > limit if direction == "max" else yy < limit
        alarm = pp > limit if direction == "max" else pp < limit
        result.update(
            limit=float(limit), direction=direction, near_margin=near_margin,
            actual_exceedances=int(risk.sum()),
            recall=float(alarm[risk].mean()) if risk.any() else None,
            false_alarm_rate=float(alarm[~risk].mean()) if (~risk).any() else None,
        )
        if near_margin is not None:
            near = np.abs(yy - limit) <= near_margin
            result["mae_near_limit"] = float(np.abs(yy[near] - pp[near]).mean()) if near.any() else None
    if lower is not None:
        lo, hi = np.asarray(lower)[valid], np.asarray(upper)[valid]
        result.update(interval_coverage=float(((yy >= lo) & (yy <= hi)).mean()),
                      mean_interval_width=float(np.mean(hi - lo)))
        if risk_configured:
            bound = hi if direction == "max" else lo
            alarm_bound = bound > limit if direction == "max" else bound < limit
            result.update(
                upper_bound_recall=float(alarm_bound[risk].mean()) if risk.any() else None,
                upper_bound_false_alarm_rate=float(alarm_bound[~risk].mean()) if (~risk).any() else None,
                below_limit_fraction=float((bound <= limit).mean()) if direction == "max" else None,
                missed_exceedances=int(((~alarm_bound) & risk).sum()),
            )
    return result


MIN_RELATIVE_GAIN = 0.05

SIMPLE_BASELINES = ("last_lab", "last_pak")


def paired_bootstrap(errors_a, errors_b, draws: int = 2000, seed: int = 0) -> dict:
    a, b = np.asarray(errors_a, float), np.asarray(errors_b, float)
    if a.shape != b.shape:
        raise ValueError("Сравнение требует одинакового набора наблюдений для обеих моделей")
    rng = np.random.default_rng(seed)
    index = rng.integers(0, len(a), size=(draws, len(a)))
    differences = a[index].mean(axis=1) - b[index].mean(axis=1)
    low, high = np.percentile(differences, [2.5, 97.5])
    return {"difference": float(a.mean() - b.mean()), "ci_low": float(low), "ci_high": float(high),
            "share_favouring_b": float((differences > 0).mean())}


def select_model(scores: dict, errors: dict, min_relative_gain: float = MIN_RELATIVE_GAIN,
                 seed: int = 0) -> dict:
    available = [name for name in SIMPLE_BASELINES if name in scores]
    if not available:
        raise ValueError("Ни один простой прогноз не участвует в сравнении")
    baseline = min(available, key=lambda n: scores[n])
    best_other = min((n for n in scores if n not in SIMPLE_BASELINES), key=lambda n: scores[n], default=None)
    decision = {"baseline": baseline, "baseline_mae": scores[baseline],
                "min_relative_gain": min_relative_gain, "challenger": best_other}
    if best_other is None:
        return decision | {"selected": baseline, "reason": "Сложных моделей в сравнении нет"}
    gain = (scores[baseline] - scores[best_other]) / scores[baseline] if scores[baseline] > 0 else 0.0
    test = paired_bootstrap(errors[baseline], errors[best_other], seed=seed)
    decision.update(challenger_mae=scores[best_other], relative_gain=float(gain), bootstrap=test)
    if gain < min_relative_gain:
        return decision | {"selected": baseline,
                           "reason": f"Выигрыш {gain:.1%} меньше минимального полезного "
                                     f"{min_relative_gain:.0%}: простой прогноз остаётся основным"}
    if test["ci_low"] <= 0:
        return decision | {"selected": baseline,
                           "reason": "Доверительный интервал разности накрывает ноль: "
                                     "преимущество не отличимо от шума"}
    return decision | {"selected": best_other,
                       "reason": f"Выигрыш {gain:.1%} превышает минимальный полезный "
                                 f"{min_relative_gain:.0%}, интервал разности не накрывает ноль"}


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
        column = "lab.target" if "lab.target" in x.columns else "lab.sulfur"
        return x[column].to_numpy()
    if name == "last_pak":
        return x["pak.sulfur"].to_numpy()
    if name == "last_pak_bc":
        return np.maximum(0, x["pak.sulfur"].to_numpy() + x["pak.lab_bias20"].to_numpy())
    model = bundle["models"][name]
    columns = bundle["columns"][name]
    return np.maximum(0, np.expm1(model.predict(x[columns])))


def run_experiment(x, meta, cfg, target: str = "actual_sulfur", limit: float | None = _UNSET,
                   direction: str = "max", near_margin: float | None = None):
    masks = split_periods(meta, cfg)
    if any(mask.sum() < 30 for mask in masks.values()):
        raise ValueError("Меньше 30 лабораторных анализов в одном из временных периодов")
    train, val, cal, test = [masks[k] for k in ("train", "validation", "calibration", "test")]
    y = meta[target].to_numpy()
    if limit is _UNSET:
        limit = cfg["sulfur_limit"] if target == "actual_sulfur" else None
        if target == "actual_sulfur" and near_margin is None:
            near_margin = cfg.get("sulfur_near_margin", 5.0)
    if limit is not None and not np.isfinite(limit):
        raise ValueError("Предел должен быть конечным или None")
    if near_margin is not None and (not np.isfinite(near_margin) or near_margin < 0):
        raise ValueError("Окрестность предела должна быть конечной и неотрицательной")
    columns = [c for c in x.columns[x.loc[train].nunique() > 1] if c != "pak.lab_bias20"]
    no_pak = [c for c in columns if not c.startswith("pak.")]
    bundle = {"models": {}, "columns": {}, "radii": {}, "config": cfg}
    own_target = "lab.target" in x.columns
    production_selection = None if own_target else validate_forecast_selection(cfg)
    sulfur_baselines = ["last_pak"]
    if production_selection:
        sulfur_baselines.append("last_pak_bc")
    candidates = ["last_lab", *([] if own_target else sulfur_baselines),
                  "ridge", "catboost", "catboost_no_pak"]
    predictions = {}
    for name in candidates:
        if name not in ("last_lab", "last_pak", "last_pak_bc"):
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
    common = val.copy()
    for p in predictions.values():
        common &= np.isfinite(p)
    if common.sum() < 30:
        raise ValueError("Недостаточно общих наблюдений для честного сравнения моделей")
    errors = {name: np.abs(y[common] - p[common]) for name, p in predictions.items()}
    scores = {name: float(e.mean()) for name, e in errors.items()}
    choice = select_model(scores, errors, cfg.get("min_relative_gain", MIN_RELATIVE_GAIN), cfg["seed"])
    selected = choice["selected"]
    if production_selection:
        selected = production_selection.get("selected")
        if selected not in candidates:
            raise ValueError(f"Замороженный production-прогноз {selected!r} отсутствует среди кандидатов")
        if pd.Timestamp(production_selection.get("development_end")) > pd.Timestamp(cfg["calibration_end"]):
            raise ValueError("Production-прогноз выбран с использованием данных после границы разработки")
    bundle["selected"] = selected
    bundle["selection_decision"] = choice
    bundle["production_selection"] = production_selection
    bundle["fallback"] = "catboost_no_pak"
    bundle["candidates"] = candidates
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
            "validation": metrics(y[val], prediction[val], limit,
                                   direction=direction, near_margin=near_margin),
            "test": metrics(y[test], prediction[test], limit, lo[test], hi[test],
                             direction=direction, near_margin=near_margin),
            "test_common": metrics(y[common_test], prediction[common_test], limit,
                                    lo[common_test], hi[common_test],
                                    direction=direction, near_margin=near_margin),
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
        "selected": selected, "target": target, "limit": limit,
        "direction": direction, "near_margin": near_margin,
        "selection": ("Заранее зарегистрированный rolling-выбор до 2026; test не участвует"
                      if production_selection else
                      "MAE на общем наборе validation с минимальным полезным отрывом и парным "
                      "бутстрепом разности; тест не участвует"),
        "selection_decision": choice,
        "production_selection": production_selection,
        "validation_common_n": int(common.sum()),
        "test_common_n": int(common_test.sum()),
        "periods": {name: {"n": int(m.sum()), "first_decision": str(meta.loc[m, "decision_time"].min()),
                           "last_target": str(meta.loc[m, "target_time"].max())} for name, m in masks.items()},
        "excluded_boundary_rows": int((~np.logical_or.reduce(list(masks.values()))).sum()),
        "models": results, "assumptions": cfg["assumptions"],
        "scope": "Прогноз за 2 часа до времени реальной пробы. Один анализ — одна целевая строка. Не эффект управления.",
    }
    return bundle, summary, output
