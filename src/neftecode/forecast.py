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


#: A complex model must beat the best simple baseline by at least this share of its error
#: before it is allowed to replace it. Chosen because the observed gap in T05 was 0.3%,
#: which is indistinguishable from noise on 174 analyses.
MIN_RELATIVE_GAIN = 0.05

#: Baselines that require no fitting. One of them stays in charge unless clearly beaten.
SIMPLE_BASELINES = ("last_lab", "last_pak")


def paired_bootstrap(errors_a, errors_b, draws: int = 2000, seed: int = 0) -> dict:
    """Confidence interval of the MAE difference on the SAME analyses.

    Paired resampling: comparing two models on different subsets would let availability
    masquerade as accuracy.
    """
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
    """Pick a model, keeping the simple baseline unless the gain is real and useful.

    Two conditions must both hold for a fitted model to win: the improvement is at least
    `min_relative_gain` of the baseline error, and a paired bootstrap interval of the
    difference excludes zero.
    """
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
        # Persistence of the target property itself when it differs from sulfur.
        column = "lab.target" if "lab.target" in x.columns else "lab.sulfur"
        return x[column].to_numpy()
    if name == "last_pak":
        return x["pak.sulfur"].to_numpy()
    model = bundle["models"][name]
    columns = bundle["columns"][name]
    return np.maximum(0, np.expm1(model.predict(x[columns])))


def run_experiment(x, meta, cfg, target: str = "actual_sulfur", limit: float | None = None):
    masks = split_periods(meta, cfg)
    if any(mask.sum() < 30 for mask in masks.values()):
        raise ValueError("Меньше 30 лабораторных анализов в одном из временных периодов")
    train, val, cal, test = [masks[k] for k in ("train", "validation", "calibration", "test")]
    y = meta[target].to_numpy()
    limit = cfg["sulfur_limit"] if limit is None else limit
    columns = x.columns[x.loc[train].nunique() > 1].tolist()
    no_pak = [c for c in columns if not c.startswith("pak.")]
    bundle = {"models": {}, "columns": {}, "radii": {}, "config": cfg}
    # The online analyser measures sulfur only: it is not a baseline for any other property.
    own_target = "lab.target" in x.columns
    candidates = ["last_lab", *([] if own_target else ["last_pak"]), "ridge", "catboost", "catboost_no_pak"]
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
    errors = {name: np.abs(y[common] - p[common]) for name, p in predictions.items()}
    scores = {name: float(e.mean()) for name, e in errors.items()}
    choice = select_model(scores, errors, cfg.get("min_relative_gain", MIN_RELATIVE_GAIN), cfg["seed"])
    selected = choice["selected"]
    bundle["selected"] = selected
    bundle["selection_decision"] = choice
    # Fallback is evaluated separately; never claim it retains the main model's accuracy.
    bundle["fallback"] = "catboost_no_pak"
    bundle["candidates"] = candidates
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
            "test": metrics(y[test], prediction[test], limit, lo[test], hi[test]),
            "test_common": metrics(y[common_test], prediction[common_test], limit, lo[common_test], hi[common_test]),
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
        "selection": "MAE на общем наборе validation с минимальным полезным отрывом и парным "
                     "бутстрепом разности; тест не участвует",
        "selection_decision": choice,
        "validation_common_n": int(common.sum()),
        "test_common_n": int(common_test.sum()),
        "periods": {name: {"n": int(m.sum()), "first_decision": str(meta.loc[m, "decision_time"].min()),
                           "last_target": str(meta.loc[m, "target_time"].max())} for name, m in masks.items()},
        "excluded_boundary_rows": int((~np.logical_or.reduce(list(masks.values()))).sum()),
        "models": results, "assumptions": cfg["assumptions"],
        "scope": "Прогноз за 2 часа до времени реальной пробы. Один анализ — одна целевая строка. Не эффект управления.",
    }
    return bundle, summary, output
