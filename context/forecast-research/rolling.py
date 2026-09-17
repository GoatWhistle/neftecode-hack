"""T104–T107: causal rolling evaluation of the sulfur forecast.

Run from the repository root:

    AGENTIC_DECISION_ENABLED=0 .venv/bin/python context/forecast-research/rolling.py

The development run is hard-stopped before 2026.  The final 2026 evaluation is
implemented separately in T108 so it cannot accidentally influence this report.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from neftecode.infrastructure.data.data import (
    derive_source_rules,
    load_sources,
    make_dataset,
    split_periods,
)
from neftecode.infrastructure.ml.forecast import calibrate, interval, metrics, predict_candidate


ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = Path(__file__).resolve().parent
DEVELOPMENT_END = pd.Timestamp("2026-01-01")
FOLDS = (
    ("2023 H2", pd.Timestamp("2023-07-01"), pd.Timestamp("2024-01-01")),
    ("2024 H1", pd.Timestamp("2024-01-01"), pd.Timestamp("2024-07-01")),
    ("2024 H2", pd.Timestamp("2024-07-01"), pd.Timestamp("2025-01-01")),
    ("2025 H1", pd.Timestamp("2025-01-01"), pd.Timestamp("2025-07-01")),
    ("2025 H2", pd.Timestamp("2025-07-01"), pd.Timestamp("2026-01-01")),
)
ACI_POINT_CANDIDATES = ("last_pak_bc_n20", "catboost_residual")
ACI_SELECTED_POINT = "last_pak_bc_n20"


def read_config() -> dict[str, Any]:
    with (ROOT / "config/experiment.json").open() as stream:
        return json.load(stream)


def pre2026_sources(dead_until: pd.Timestamp):
    """Load sources with fold-specific dead-column rules, then discard 2026."""
    signals, lab, online = load_sources(ROOT / "task", dead_until)
    signals = signals.loc[signals.index < DEVELOPMENT_END].copy()
    lab = lab.loc[lab.time < DEVELOPMENT_END].copy()
    online = online.loc[online.time < DEVELOPMENT_END].copy()
    if signals.empty or lab.empty or online.empty:
        raise ValueError("После причинного отсечения до 2026 один из источников пуст")
    if (
        signals.index.max() >= DEVELOPMENT_END
        or lab.time.max() >= DEVELOPMENT_END
        or online.time.max() >= DEVELOPMENT_END
    ):
        raise AssertionError("Стенд разработки увидел строку 2026 года")
    return signals, lab, online


def catboost(cfg: dict[str, Any]) -> CatBoostRegressor:
    return CatBoostRegressor(
        iterations=300,
        depth=4,
        learning_rate=0.035,
        loss_function="MAE",
        random_seed=cfg["seed"],
        thread_count=2,
        verbose=False,
        allow_writing_files=False,
    )


def pak_lab_pairs(lab: pd.DataFrame, online: pd.DataFrame, delay_hours: float) -> pd.DataFrame:
    """Pair each lab sample with the last PAK reading available at sample time.

    This is deliberately the same 30-minute backward tolerance as ``pak_at_lab``
    in ``build_features``.  A pair becomes usable only when the lab result does.
    """
    pak = online.set_index("time").value
    pak.index = pd.DatetimeIndex(pak.index).as_unit("ns")
    sample_times = pd.DatetimeIndex(lab.time).as_unit("ns")
    pak_values = pak.reindex(
        sample_times,
        method="ffill",
        tolerance=np.timedelta64(30, "m"),
    ).to_numpy()
    pairs = pd.DataFrame(
        {
            "sample_time": sample_times,
            "available_time": sample_times + np.timedelta64(round(delay_hours * 3600), "s"),
            "bias": lab.value.to_numpy() - pak_values,
        }
    )
    return pairs.loc[np.isfinite(pairs.bias)].sort_values("available_time").reset_index(drop=True)


def causal_bias_correction(
    decision_times,
    pairs: pd.DataFrame,
    window: int,
    min_pairs: int = 5,
) -> np.ndarray:
    """Median of the last ``window`` pairs known at each decision time."""
    if window < min_pairs or min_pairs < 1:
        raise ValueError("Окно поправки должно быть не меньше минимального числа пар")
    times = pd.DatetimeIndex(decision_times)
    order = np.argsort(times.to_numpy())
    known = pairs.sort_values("available_time").reset_index(drop=True)
    available = known.available_time.to_numpy(dtype="datetime64[ns]")
    values = known.bias.to_numpy(float)
    result = np.zeros(len(times), dtype=float)
    right = 0
    for position in order:
        current = times[position].to_datetime64()
        while right < len(known) and available[right] <= current:
            right += 1
        result[position] = float(np.median(values[max(0, right - window):right])) if right >= min_pairs else 0.0
    return result


def sign_changes(values) -> int:
    signs = np.sign(np.asarray(values, float))
    signs = signs[signs != 0]
    return int(np.sum(signs[1:] != signs[:-1])) if len(signs) > 1 else 0


def check_bias_causality(
    decision_times,
    pairs: pd.DataFrame,
    windows: tuple[int, ...] = (10, 20, 40),
) -> dict[str, Any]:
    """Check that adding lab results available later cannot change b(t)."""
    times = pd.DatetimeIndex(decision_times)
    positions = np.unique(np.linspace(0, len(times) - 1, min(9, len(times)), dtype=int))
    checked = 0
    for position in positions:
        at = times[position]
        past = pairs.loc[pairs.available_time <= at]
        for window in windows:
            with_future = causal_bias_correction([at], pairs, window)[0]
            without_future = causal_bias_correction([at], past, window)[0]
            if not np.isclose(with_future, without_future, rtol=0, atol=0):
                raise AssertionError(f"Будущая проба изменила поправку в {at} для N={window}")
            checked += 1
    return {"passed": True, "checked_time_window_pairs": checked}


def combine_residual_prediction(last_pak, predicted_log_residual, fallback) -> np.ndarray:
    """Apply a log-residual where PAK exists, otherwise retain no-PAK fallback."""
    last_pak = np.asarray(last_pak, float)
    predicted_log_residual = np.asarray(predicted_log_residual, float)
    result = np.asarray(fallback, float).copy()
    available = np.isfinite(last_pak)
    result[available] = np.maximum(
        0,
        np.expm1(np.log1p(last_pak[available]) + predicted_log_residual[available]),
    )
    return result


def conformal_upper_quantile(residuals, alpha: float) -> float:
    values = np.sort(np.asarray(residuals, float))
    values = values[np.isfinite(values)]
    if not len(values):
        raise ValueError("Для адаптивной границы нет остатков")
    rank = min(math.ceil((len(values) + 1) * (1 - alpha)), len(values))
    return float(values[rank - 1])


def adaptive_upper_bounds(
    meta: pd.DataFrame,
    y: np.ndarray,
    point: np.ndarray,
    calibration: np.ndarray,
    evaluation: np.ndarray,
    gamma: float,
    window: int = 100,
    target_alpha: float = 0.05,
) -> dict[str, np.ndarray]:
    """Prequential ACI: update only after the issued forecast's target is known."""
    if not 0 < gamma < 1 or window < 30 or not 0 < target_alpha < 1:
        raise ValueError("Некорректные параметры ACI")
    y = np.asarray(y, float)
    point = np.asarray(point, float)
    calibration_rows = np.flatnonzero(calibration & np.isfinite(point))
    if len(calibration_rows) < 30:
        raise ValueError("Для начального окна ACI нужно не меньше 30 остатков")
    calibration_rows = calibration_rows[
        np.argsort(meta.target_available_time.to_numpy()[calibration_rows])
    ]
    residual_window = list(
        (np.log1p(y[calibration_rows]) - np.log1p(point[calibration_rows]))[-window:]
    )

    upper = np.full(len(meta), np.nan)
    alpha_at_issue = np.full(len(meta), np.nan)
    q_at_issue = np.full(len(meta), np.nan)
    error_at_issue = np.full(len(meta), np.nan)
    alpha = target_alpha
    pending: list[tuple[pd.Timestamp, int, float]] = []
    evaluation_rows = np.flatnonzero(evaluation)
    evaluation_rows = evaluation_rows[np.argsort(meta.decision_time.to_numpy()[evaluation_rows])]

    for row in evaluation_rows:
        decision_time = pd.Timestamp(meta.decision_time.iloc[row])
        ready = sorted((item for item in pending if item[0] <= decision_time), key=lambda item: item[0])
        pending = [item for item in pending if item[0] > decision_time]
        for _, previous_row, issued_upper in ready:
            error = float(y[previous_row] > issued_upper)
            error_at_issue[previous_row] = error
            alpha = float(np.clip(alpha + gamma * (target_alpha - error), 0.001, 0.999))
            residual = float(np.log1p(y[previous_row]) - np.log1p(point[previous_row]))
            residual_window.append(residual)
            residual_window = residual_window[-window:]

        if not np.isfinite(point[row]):
            continue
        q = conformal_upper_quantile(residual_window, alpha)
        issued_upper = float(np.expm1(np.log1p(point[row]) + q))
        upper[row] = issued_upper
        alpha_at_issue[row] = alpha
        q_at_issue[row] = q
        pending.append((pd.Timestamp(meta.target_available_time.iloc[row]), row, issued_upper))

    return {
        "upper": upper,
        "alpha": alpha_at_issue,
        "q": q_at_issue,
        "error": error_at_issue,
    }


def fixed_split_check(base_cfg: dict[str, Any]) -> dict[str, Any]:
    """Reproduce the existing 2025-H1 validation comparison exactly.

    The common mask includes all five current methods, matching run_experiment.
    This is a harness check, not one of the rolling folds.
    """
    train_end = pd.Timestamp(base_cfg["train_end"])
    signals, lab, online = pre2026_sources(train_end)
    rules = derive_source_rules(signals, lab, online, train_end, base_cfg)
    cfg = {**base_cfg, **rules}
    x, meta = make_dataset(signals, lab, online, cfg)
    masks = split_periods(meta, cfg)
    train, validation = masks["train"], masks["validation"]
    y = meta.actual_sulfur.to_numpy()
    columns = x.columns[x.loc[train].nunique() > 1].tolist()
    no_pak = [column for column in columns if not column.startswith("pak.")]

    bundle: dict[str, Any] = {"models": {}, "columns": {}}
    predictions: dict[str, np.ndarray] = {}
    ridge = make_pipeline(
        SimpleImputer(strategy="median", add_indicator=True),
        StandardScaler(),
        Ridge(alpha=100),
    )
    for name, model, model_columns in (
        ("ridge", ridge, columns),
        ("catboost", catboost(cfg), columns),
        ("catboost_no_pak", catboost(cfg), no_pak),
    ):
        model.fit(x.loc[train, model_columns], np.log1p(y[train]))
        bundle["models"][name] = model
        bundle["columns"][name] = model_columns
    for name in ("last_lab", "last_pak", "ridge", "catboost", "catboost_no_pak"):
        predictions[name] = predict_candidate(bundle, name, x)

    common = validation.copy()
    for prediction in predictions.values():
        common &= np.isfinite(prediction)
    if common.sum() < 30:
        raise ValueError("Недостаточно общих строк в контрольном fixed split")
    actual = {
        name: float(np.mean(np.abs(y[common] - prediction[common])))
        for name, prediction in predictions.items()
    }
    with (ROOT / "artifacts/metrics.json").open() as stream:
        artifact = json.load(stream)
    expected = {
        name: float(artifact["models"][name]["validation_common_mae"])
        for name in ("last_pak", "catboost_no_pak")
    }
    differences = {name: actual[name] - expected[name] for name in expected}
    if any(abs(value) > 1e-6 for value in differences.values()):
        raise AssertionError(
            "Контрольный fixed split не воспроизведён до 1e-6: "
            + ", ".join(f"{name}={value:+.9f}" for name, value in differences.items())
        )
    return {
        "period": "2025 H1",
        "common_n": int(common.sum()),
        "actual_mae": {name: actual[name] for name in expected},
        "artifact_mae": expected,
        "difference": differences,
        "tolerance": 1e-6,
        "passed": True,
    }


def evaluate(
    y: np.ndarray,
    prediction: np.ndarray,
    evaluation: np.ndarray,
    radius: float,
    cfg: dict[str, Any],
) -> dict[str, Any]:
    lower, upper = interval(prediction, radius)
    result = evaluate_bounds(y, prediction, evaluation, lower, upper, cfg)
    result["radius"] = float(radius)
    return result


def evaluate_bounds(
    y: np.ndarray,
    prediction: np.ndarray,
    evaluation: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
    cfg: dict[str, Any],
) -> dict[str, Any]:
    selected = evaluation & np.isfinite(prediction) & np.isfinite(lower) & np.isfinite(upper)
    if not selected.any():
        raise ValueError("У метода нет доступных прогнозов в складке")
    result = metrics(
        y[evaluation],
        prediction[evaluation],
        cfg["sulfur_limit"],
        lower[evaluation],
        upper[evaluation],
        direction="max",
        near_margin=cfg.get("sulfur_near_margin", 5.0),
    )
    result.update(
        exceed_upper=float(np.mean(y[selected] > upper[selected])),
        one_sided_coverage=float(np.mean(y[selected] <= upper[selected])),
        mean_upper_margin=float(np.mean(upper[selected] - prediction[selected])),
    )
    return result


def rolling_fold(
    name: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    base_cfg: dict[str, Any],
) -> dict[str, Any]:
    if end > DEVELOPMENT_END:
        raise ValueError("T104–T107 запрещено оценивать 2026 год")
    # The source starts in January 2023.  The protocol therefore reserves Q1
    # for fit and Q2 for calibration in the first fold; later folds use 6 months.
    calibration_months = 3 if start == FOLDS[0][1] else 6
    calibration_start = start - pd.DateOffset(months=calibration_months)
    signals, lab, online = pre2026_sources(start)
    rules = derive_source_rules(signals, lab, online, start, base_cfg)
    cfg = {**base_cfg, **rules}
    x, meta = make_dataset(signals, lab, online, cfg)
    y = meta.actual_sulfur.to_numpy()
    pairs = pak_lab_pairs(lab, online, cfg["lab_delay_hours"])

    fit = (meta.target_available_time < calibration_start).to_numpy()
    calibration = (
        (meta.target_available_time >= calibration_start)
        & (meta.target_available_time < start)
    ).to_numpy()
    evaluation = (
        (meta.decision_time >= start) & (meta.target_available_time < end)
    ).to_numpy()
    counts = {"fit": int(fit.sum()), "calibration": int(calibration.sum()), "evaluation": int(evaluation.sum())}
    if any(value < 30 for value in counts.values()):
        raise ValueError(f"{name}: меньше 30 строк в части складки: {counts}")

    columns = x.columns[x.loc[fit].nunique() > 1].tolist()
    no_pak = [column for column in columns if not column.startswith("pak.")]
    no_pak_model = catboost(cfg)
    no_pak_model.fit(x.loc[fit, no_pak], np.log1p(y[fit]))
    bundle = {
        "models": {"catboost_no_pak": no_pak_model},
        "columns": {"catboost_no_pak": no_pak},
    }
    predictions = {
        method: predict_candidate(bundle, method, x)
        for method in ("last_pak", "catboost_no_pak")
    }
    residual_fit = fit & np.isfinite(predictions["last_pak"])
    if residual_fit.sum() < 30:
        raise ValueError(f"{name}: недостаточно доступных ПАК для CatBoost остатка")
    residual_target = np.log1p(y[residual_fit]) - np.log1p(predictions["last_pak"][residual_fit])
    residual_model = catboost(cfg)
    residual_model.fit(x.loc[residual_fit, columns], residual_target)
    predicted_log_residual = residual_model.predict(x[columns])
    predictions["catboost_residual"] = combine_residual_prediction(
        predictions["last_pak"],
        predicted_log_residual,
        predictions["catboost_no_pak"],
    )
    corrections = {}
    for window in (10, 20, 40):
        method = f"last_pak_bc_n{window}"
        corrections[method] = causal_bias_correction(meta.decision_time, pairs, window)
        predictions[method] = np.maximum(0, predictions["last_pak"] + corrections[method])
    method_results = {}
    bounds = {}
    for method, prediction in tuple(predictions.items()):
        radius = calibrate(y[calibration], prediction[calibration], cfg["interval_coverage"])
        method_results[method] = evaluate(y, prediction, evaluation, radius, cfg)
        bounds[method] = interval(prediction, radius)

    aci_states = {}
    for point_method in ("last_pak", ACI_SELECTED_POINT):
        point = predictions[point_method]
        fixed_lower, _ = bounds[point_method]
        for gamma, gamma_name in ((0.005, "g0005"), (0.01, "g001"), (0.02, "g002")):
            method = f"aci_{point_method}_{gamma_name}_m100"
            state = adaptive_upper_bounds(meta, y, point, calibration, evaluation, gamma=gamma, window=100)
            predictions[method] = point.copy()
            bounds[method] = (fixed_lower.copy(), state["upper"])
            method_results[method] = evaluate_bounds(
                y,
                predictions[method],
                evaluation,
                bounds[method][0],
                bounds[method][1],
                cfg,
            )
            issued = evaluation & np.isfinite(state["upper"])
            realized_error = np.full(len(meta), np.nan)
            realized_error[issued] = (y[issued] > state["upper"][issued]).astype(float)
            rolling30 = pd.Series(realized_error[issued]).rolling(30, min_periods=30).mean().to_numpy()
            finite_alpha = state["alpha"][issued]
            finite_q = state["q"][issued]
            method_results[method].update(
                point_method=point_method,
                gamma=gamma,
                window=100,
                alpha_mean=float(np.mean(finite_alpha)),
                alpha_min=float(np.min(finite_alpha)),
                alpha_max=float(np.max(finite_alpha)),
                q_mean=float(np.mean(finite_q)),
                state_updates=int(np.isfinite(state["error"]).sum()),
                rolling30_max=float(np.nanmax(rolling30)) if np.isfinite(rolling30).any() else None,
                rolling30_last=float(rolling30[np.isfinite(rolling30)][-1]) if np.isfinite(rolling30).any() else None,
            )
            state["realized_error"] = realized_error
            state["rolling30"] = np.full(len(meta), np.nan)
            state["rolling30"][np.flatnonzero(issued)] = rolling30
            aci_states[method] = state

    common = evaluation.copy()
    for prediction in predictions.values():
        common &= np.isfinite(prediction)
    if common.sum() < 30:
        raise ValueError(f"{name}: недостаточно общих прогнозов")
    for method, prediction in predictions.items():
        method_results[method]["common_mae"] = float(np.mean(np.abs(y[common] - prediction[common])))
    method_results["catboost_residual"].update(
        fit_with_pak=int(residual_fit.sum()),
        evaluation_fallback_rows=int(np.sum(evaluation & ~np.isfinite(predictions["last_pak"]))),
    )
    base_valid = evaluation & np.isfinite(predictions["last_pak"])
    for method, correction in corrections.items():
        valid = base_valid & np.isfinite(predictions[method])
        method_results[method].update(
            mean_bias_before=float(np.mean(y[valid] - predictions["last_pak"][valid])),
            mean_bias_after=float(np.mean(y[valid] - predictions[method][valid])),
            correction_mean=float(np.mean(correction[valid])),
            correction_median=float(np.median(correction[valid])),
            correction_sign_changes=sign_changes(correction[valid]),
        )

    rows = meta.loc[evaluation, ["decision_time", "target_time", "target_available_time", "actual_sulfur"]].copy()
    rows.insert(0, "fold", name)
    for method, prediction in predictions.items():
        lower, upper = bounds[method]
        rows[method] = prediction[evaluation]
        rows[f"{method}_lower"] = lower[evaluation]
        rows[f"{method}_upper"] = upper[evaluation]
        if method in corrections:
            rows[f"{method}_correction"] = corrections[method][evaluation]
        if method in aci_states:
            state = aci_states[method]
            rows[f"{method}_alpha"] = state["alpha"][evaluation]
            rows[f"{method}_q"] = state["q"][evaluation]
            rows[f"{method}_error"] = state["realized_error"][evaluation]
            rows[f"{method}_exceed30"] = state["rolling30"][evaluation]
    return {
        "fold": name,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "calibration_start": calibration_start.isoformat(),
        "counts": counts | {"common": int(common.sum())},
        "feature_counts": {"all": len(columns), "no_pak": len(no_pak)},
        "source_rules": {key: value for key, value in rules.items() if key != "source_rules"},
        "bias_causality": check_bias_causality(meta.loc[evaluation, "decision_time"], pairs),
        "methods": method_results,
        "_rows": rows,
    }


def mean(values) -> float | None:
    clean = [float(value) for value in values if value is not None and np.isfinite(value)]
    return float(np.mean(clean)) if clean else None


def aggregate(folds: list[dict[str, Any]]) -> dict[str, Any]:
    keys = (
        "mae",
        "common_mae",
        "exceed_upper",
        "one_sided_coverage",
        "interval_coverage",
        "mean_interval_width",
        "mean_upper_margin",
        "recall",
        "false_alarm_rate",
        "upper_bound_recall",
        "upper_bound_false_alarm_rate",
        "mean_bias_before",
        "mean_bias_after",
        "correction_mean",
        "correction_median",
    )
    result = {}
    methods = tuple(folds[0]["methods"])
    for method in methods:
        result[method] = {
            key: mean(fold["methods"][method].get(key) for fold in folds)
            for key in keys
        }
        result[method]["worst_fold_exceed_upper"] = max(
            fold["methods"][method]["exceed_upper"] for fold in folds
        )
        result[method]["total_predicted"] = sum(
            fold["methods"][method]["predicted"] for fold in folds
        )
        result[method]["total_evaluation"] = sum(
            fold["methods"][method]["n"] for fold in folds
        )
        if all("correction_sign_changes" in fold["methods"][method] for fold in folds):
            result[method]["correction_sign_changes"] = sum(
                fold["methods"][method]["correction_sign_changes"] for fold in folds
            )
    return result


def paired_bootstrap_by_fold(
    rows: pd.DataFrame,
    candidate: str,
    draws: int = 2000,
    seed: int = 42,
) -> dict[str, float | int]:
    """Paired row bootstrap within each fold; folds retain equal weight."""
    rng = np.random.default_rng(seed)
    differences = np.zeros(draws, dtype=float)
    fold_differences = []
    for fold_name, fold in rows.groupby("fold", sort=False):
        valid = fold[["actual_sulfur", "last_pak", candidate]].notna().all(axis=1)
        actual = fold.loc[valid, "actual_sulfur"].to_numpy(float)
        baseline_error = np.abs(actual - fold.loc[valid, "last_pak"].to_numpy(float))
        candidate_error = np.abs(actual - fold.loc[valid, candidate].to_numpy(float))
        if len(actual) < 30:
            raise ValueError(f"{fold_name}: меньше 30 парных строк для bootstrap")
        indices = rng.integers(0, len(actual), size=(draws, len(actual)))
        differences += (candidate_error[indices].mean(axis=1) - baseline_error[indices].mean(axis=1)) / len(FOLDS)
        fold_differences.append(float(candidate_error.mean() - baseline_error.mean()))
    low, high = np.percentile(differences, [2.5, 97.5])
    return {
        "draws": draws,
        "seed": seed,
        "difference_candidate_minus_baseline": float(np.mean(fold_differences)),
        "ci_low": float(low),
        "ci_high": float(high),
        "share_candidate_better": float(np.mean(differences < 0)),
    }


def selection_gate(candidate: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    conditions = {
        "mean_exceed_at_most_005": candidate["exceed_upper"] <= 0.05,
        "worst_fold_no_worse": candidate["worst_fold_exceed_upper"] <= baseline["worst_fold_exceed_upper"],
        "width_or_closer_coverage": (
            candidate["mean_upper_margin"] <= baseline["mean_upper_margin"]
            or (
                abs(candidate["exceed_upper"] - 0.05) < abs(baseline["exceed_upper"] - 0.05)
                and candidate["mean_upper_margin"] <= 1.10 * baseline["mean_upper_margin"]
            )
        ),
        "mae_within_5_percent": candidate["common_mae"] <= 1.05 * baseline["common_mae"],
    }
    return {"conditions": conditions, "eligible": all(conditions.values())}


def choose_aci_point(aggregate_result: dict[str, Any]) -> str:
    order = {name: position for position, name in enumerate(ACI_POINT_CANDIDATES)}
    return min(
        ACI_POINT_CANDIDATES,
        key=lambda name: (
            abs(aggregate_result[name]["exceed_upper"] - 0.05),
            aggregate_result[name]["mean_upper_margin"],
            aggregate_result[name]["common_mae"],
            order[name],
        ),
    )


def fmt(value: float | None, digits: int = 3) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def render_markdown(result: dict[str, Any]) -> str:
    check = result["fixed_split_check"]
    lines = [
        "# Результаты скользящей проверки прогноза серы",
        "",
        "Протокол зафиксирован в `protocol.md` до этих расчётов. Ни одна строка 2026 года",
        "не входит в fit, калибровку или оценку T104–T107.",
        "",
        "## T104. Стенд и текущий вариант",
        "",
        "Контрольный fixed split 2025 H1 воспроизведён с допуском 1e-6 на общем наборе",
        f"из {check['common_n']} проб: `last_pak` {check['actual_mae']['last_pak']:.9f},",
        f"`catboost_no_pak` {check['actual_mae']['catboost_no_pak']:.9f}. Контроль пройден.",
        "",
        "Rolling отличается от прежнего fixed split: калибровочное окно перед полугодием исключено",
        "из fit CatBoost (6 месяцев; для первой складки 3 месяца из-за начала данных).",
        "",
        "| Складка | fit / cal / eval | Общие | last_pak MAE | exceed upper | 2-side cov | upper margin | no-PAK MAE | no-PAK exceed |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for fold in result["folds"]:
        lp = fold["methods"]["last_pak"]
        cb = fold["methods"]["catboost_no_pak"]
        counts = fold["counts"]
        lines.append(
            f"| {fold['fold']} | {counts['fit']} / {counts['calibration']} / {counts['evaluation']} "
            f"| {counts['common']} | {fmt(lp['common_mae'])} | {fmt(lp['exceed_upper'])} "
            f"| {fmt(lp['interval_coverage'])} | {fmt(lp['mean_upper_margin'])} "
            f"| {fmt(cb['common_mae'])} | {fmt(cb['exceed_upper'])} |"
        )
    aggregate_result = result["aggregate"]
    lp = aggregate_result["last_pak"]
    cb = aggregate_result["catboost_no_pak"]
    lines.extend(
        [
            f"| **Среднее складок** | — | — | **{fmt(lp['common_mae'])}** | **{fmt(lp['exceed_upper'])}** "
            f"| **{fmt(lp['interval_coverage'])}** | **{fmt(lp['mean_upper_margin'])}** "
            f"| **{fmt(cb['common_mae'])}** | **{fmt(cb['exceed_upper'])}** |",
            "",
            "Среднее — невзвешенное по пяти складкам, как объявлено в протоколе. Полные значения,",
            "пороговые recall/false alarm, радиусы, правила доверия и размеры признаков находятся в",
            "`rolling-baseline.json`.",
            "",
            "Промежуточный вывод T104: стенд воспроизводит прежний контроль. Решение о замене модели",
            "не принимается до завершения F2–F4.",
            "",
        ]
    )
    f2 = result["f2"]
    lines.extend(
        [
            "## T105. Поправка смещения ПАК–ЛИМС",
            "",
            "Основной вариант использует медиану 20 последних пар, доступных к моменту решения;",
            "N=10 и N=40 — только чувствительность. Будущие ЛИМС не меняют прошлую поправку:",
            f"пройдено {f2['causality_checks']} проверок времени/окна плюс отдельный синтетический тест.",
            "",
            "| Складка | bias до → после | median b | смены знака | MAE N20 | exceed N20 | 2-side cov | upper margin | exceed N10 / N40 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for fold in result["folds"]:
        main = fold["methods"]["last_pak_bc_n20"]
        n10 = fold["methods"]["last_pak_bc_n10"]
        n40 = fold["methods"]["last_pak_bc_n40"]
        lines.append(
            f"| {fold['fold']} | {fmt(main['mean_bias_before'])} → {fmt(main['mean_bias_after'])} "
            f"| {fmt(main['correction_median'])} | {main['correction_sign_changes']} "
            f"| {fmt(main['common_mae'])} | {fmt(main['exceed_upper'])} "
            f"| {fmt(main['interval_coverage'])} | {fmt(main['mean_upper_margin'])} "
            f"| {fmt(n10['exceed_upper'])} / {fmt(n40['exceed_upper'])} |"
        )
    aggregate_result = result["aggregate"]
    main = aggregate_result["last_pak_bc_n20"]
    n10 = aggregate_result["last_pak_bc_n10"]
    n40 = aggregate_result["last_pak_bc_n40"]
    bootstrap = f2["bootstrap"]["last_pak_bc_n20"]
    gate = f2["selection_gate_n20"]
    verdict = (
        "N=20 проходит предварительный протокол F0. Финальный выбор возможен только после F3–F4."
        if gate["eligible"]
        else "N=20 не проходит предварительный протокол F0; отрицательный результат сохраняется."
    )
    lines.extend(
        [
            f"| **Среднее/сумма** | **{fmt(main['mean_bias_before'])} → {fmt(main['mean_bias_after'])}** "
            f"| **{fmt(main['correction_median'])}** | **{main['correction_sign_changes']}** "
            f"| **{fmt(main['common_mae'])}** | **{fmt(main['exceed_upper'])}** "
            f"| **{fmt(main['interval_coverage'])}** | **{fmt(main['mean_upper_margin'])}** "
            f"| **{fmt(n10['exceed_upper'])} / {fmt(n40['exceed_upper'])}** |",
            "",
            f"Парный bootstrap MAE (кандидат − база): {bootstrap['difference_candidate_minus_baseline']:.3f} мг/кг, "
            f"95% CI [{bootstrap['ci_low']:.3f}; {bootstrap['ci_high']:.3f}], "
            f"доля выборок в пользу кандидата {bootstrap['share_candidate_better']:.3f}.",
            "",
            "Условия F0 для N=20: "
            + ", ".join(f"{name}={'да' if passed else 'нет'}" for name, passed in gate["conditions"].items())
            + ".",
            verdict,
            "",
            "Полные результаты находятся в `rolling-f2.json`, строки прогнозов — в",
            "`rolling-predictions.csv`.",
            "",
        ]
    )
    f3 = result["f3"]
    lines.extend(
        [
            "## T106. CatBoost log-остатка к last_pak",
            "",
            "Модель использует тот же набор признаков и те же гиперпараметры, что текущий CatBoost.",
            "При недоступном ПАК точка берётся из `catboost_no_pak`; настройки по складкам не подбирались.",
            "",
            "| Складка | fit с ПАК | fallback eval | MAE | point recall | exceed upper | 2-side cov | upper margin |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for fold in result["folds"]:
        method = fold["methods"]["catboost_residual"]
        lines.append(
            f"| {fold['fold']} | {method['fit_with_pak']} | {method['evaluation_fallback_rows']} "
            f"| {fmt(method['common_mae'])} | {fmt(method['recall'])} "
            f"| {fmt(method['exceed_upper'])} | {fmt(method['interval_coverage'])} "
            f"| {fmt(method['mean_upper_margin'])} |"
        )
    residual = result["aggregate"]["catboost_residual"]
    bootstrap = f3["bootstrap"]
    gate = f3["selection_gate"]
    verdict = (
        "F3 проходит предварительный протокол F0. Финальный выбор возможен только после F4."
        if gate["eligible"]
        else "F3 не проходит предварительный протокол F0; отрицательный результат сохраняется."
    )
    lines.extend(
        [
            f"| **Среднее** | — | — | **{fmt(residual['common_mae'])}** | **{fmt(residual['recall'])}** "
            f"| **{fmt(residual['exceed_upper'])}** | **{fmt(residual['interval_coverage'])}** "
            f"| **{fmt(residual['mean_upper_margin'])}** |",
            "",
            f"Парный bootstrap MAE (кандидат − база): {bootstrap['difference_candidate_minus_baseline']:.3f} мг/кг, "
            f"95% CI [{bootstrap['ci_low']:.3f}; {bootstrap['ci_high']:.3f}], "
            f"доля выборок в пользу кандидата {bootstrap['share_candidate_better']:.3f}.",
            "",
            "Условия F0 для F3: "
            + ", ".join(f"{name}={'да' if passed else 'нет'}" for name, passed in gate["conditions"].items())
            + ".",
            verdict,
            "",
            "Полные результаты T106 находятся в `rolling-f3.json`.",
            "",
        ]
    )
    f4 = result["f4"]
    base_aci_name = "aci_last_pak_g001_m100"
    corrected_aci_name = "aci_last_pak_bc_n20_g001_m100"
    lines.extend(
        [
            "## T107. Адаптивная односторонняя граница",
            "",
            f"Лучшая точка для ACI по правилу протокола — `{f4['selected_point']}`. Основные варианты:",
            "gamma=0.01, M=100; gamma=0.005/0.02 остаются чувствительностью. Нижняя граница",
            "сохранена от соответствующего фиксированного симметричного интервала.",
            "",
            "| Складка | base exceed fixed → ACI | base margin fixed → ACI | F2 exceed fixed → ACI | F2 margin fixed → ACI | F2 rolling30 max / last |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for fold in result["folds"]:
        base = fold["methods"]["last_pak"]
        base_aci = fold["methods"][base_aci_name]
        corrected = fold["methods"]["last_pak_bc_n20"]
        corrected_aci = fold["methods"][corrected_aci_name]
        lines.append(
            f"| {fold['fold']} | {fmt(base['exceed_upper'])} → {fmt(base_aci['exceed_upper'])} "
            f"| {fmt(base['mean_upper_margin'])} → {fmt(base_aci['mean_upper_margin'])} "
            f"| {fmt(corrected['exceed_upper'])} → {fmt(corrected_aci['exceed_upper'])} "
            f"| {fmt(corrected['mean_upper_margin'])} → {fmt(corrected_aci['mean_upper_margin'])} "
            f"| {fmt(corrected_aci['rolling30_max'])} / {fmt(corrected_aci['rolling30_last'])} |"
        )
    aggregate_result = result["aggregate"]
    base = aggregate_result["last_pak"]
    base_aci = aggregate_result[base_aci_name]
    corrected = aggregate_result["last_pak_bc_n20"]
    corrected_aci = aggregate_result[corrected_aci_name]
    lines.extend(
        [
            f"| **Среднее** | **{fmt(base['exceed_upper'])} → {fmt(base_aci['exceed_upper'])}** "
            f"| **{fmt(base['mean_upper_margin'])} → {fmt(base_aci['mean_upper_margin'])}** "
            f"| **{fmt(corrected['exceed_upper'])} → {fmt(corrected_aci['exceed_upper'])}** "
            f"| **{fmt(corrected['mean_upper_margin'])} → {fmt(corrected_aci['mean_upper_margin'])}** | — |",
            "",
            "Чувствительность среднего `exceed_upper` (gamma 0.005 / 0.01 / 0.02):",
            f"base {fmt(aggregate_result['aci_last_pak_g0005_m100']['exceed_upper'])} / "
            f"{fmt(base_aci['exceed_upper'])} / {fmt(aggregate_result['aci_last_pak_g002_m100']['exceed_upper'])};",
            f"F2 {fmt(aggregate_result['aci_last_pak_bc_n20_g0005_m100']['exceed_upper'])} / "
            f"{fmt(corrected_aci['exceed_upper'])} / "
            f"{fmt(aggregate_result['aci_last_pak_bc_n20_g002_m100']['exceed_upper'])}.",
            "",
        ]
    )
    for method in (base_aci_name, corrected_aci_name):
        gate = f4["selection_gates"][method]
        lines.append(
            f"Условия F0 для `{method}`: "
            + ", ".join(f"{name}={'да' if passed else 'нет'}" for name, passed in gate["conditions"].items())
            + f"; итог={'проходит' if gate['eligible'] else 'не проходит'}."
        )
    lines.extend(
        [
            "",
            "Скользящая доля превышений по окну 30 проб, alpha и q для каждой выданной границы",
            "сохранены в `rolling-predictions.csv`; полные агрегаты — в `rolling-f4.json`.",
            "Окончательный победитель определяется в T108 без изменения правила F0.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    base_cfg = read_config()
    if pd.Timestamp(base_cfg["calibration_end"]) != DEVELOPMENT_END:
        raise ValueError("Граница разработки изменилась; протокол требует отдельного пересмотра")
    check = fixed_split_check(base_cfg)
    folds = [rolling_fold(name, start, end, base_cfg) for name, start, end in FOLDS]
    rows = pd.concat([fold.pop("_rows") for fold in folds], ignore_index=True)
    aggregate_result = aggregate(folds)
    selected_point = choose_aci_point(aggregate_result)
    if selected_point != ACI_SELECTED_POINT:
        raise AssertionError(
            f"Точка ACI изменилась после расчёта: ожидалась {ACI_SELECTED_POINT}, получена {selected_point}"
        )
    f2_methods = ("last_pak_bc_n10", "last_pak_bc_n20", "last_pak_bc_n40")
    f2 = {
        "causality_checks": sum(fold["bias_causality"]["checked_time_window_pairs"] for fold in folds),
        "bootstrap": {method: paired_bootstrap_by_fold(rows, method) for method in f2_methods},
        "selection_gate_n20": selection_gate(aggregate_result["last_pak_bc_n20"], aggregate_result["last_pak"]),
        "sensitivity_only": ["last_pak_bc_n10", "last_pak_bc_n40"],
    }
    f3 = {
        "bootstrap": paired_bootstrap_by_fold(rows, "catboost_residual"),
        "selection_gate": selection_gate(aggregate_result["catboost_residual"], aggregate_result["last_pak"]),
        "hyperparameters_tuned": False,
        "fallback": "catboost_no_pak",
    }
    f4_primary = ("aci_last_pak_g001_m100", "aci_last_pak_bc_n20_g001_m100")
    f4 = {
        "selected_point": selected_point,
        "point_ranking": {
            name: {
                "distance_to_005": abs(aggregate_result[name]["exceed_upper"] - 0.05),
                "mean_upper_margin": aggregate_result[name]["mean_upper_margin"],
                "common_mae": aggregate_result[name]["common_mae"],
            }
            for name in ACI_POINT_CANDIDATES
        },
        "selection_gates": {
            method: selection_gate(aggregate_result[method], aggregate_result["last_pak"])
            for method in f4_primary
        },
        "primary": list(f4_primary),
        "sensitivity_only": [
            "aci_last_pak_g0005_m100",
            "aci_last_pak_g002_m100",
            "aci_last_pak_bc_n20_g0005_m100",
            "aci_last_pak_bc_n20_g002_m100",
        ],
    }
    result = {
        "schema": "neftecode.forecast_rolling.f4.v1",
        "development_end_exclusive": DEVELOPMENT_END.isoformat(),
        "fixed_split_check": check,
        "folds": folds,
        "aggregate": aggregate_result,
        "f2": f2,
        "f3": f3,
        "f4": f4,
    }
    with (OUT_DIR / "rolling-f4.json").open("w") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    rows.to_csv(OUT_DIR / "rolling-predictions.csv", index=False)
    (OUT_DIR / "results.md").write_text(render_markdown(result), encoding="utf-8")
    print(render_markdown(result))


if __name__ == "__main__":
    main()
