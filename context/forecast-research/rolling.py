"""T104–T107: causal rolling evaluation of the sulfur forecast.

Run from the repository root:

    AGENTIC_DECISION_ENABLED=0 .venv/bin/python context/forecast-research/rolling.py

The development run is hard-stopped before 2026.  The final 2026 evaluation is
implemented separately in T108 so it cannot accidentally influence this report.
"""
from __future__ import annotations

import json
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
        radius=float(radius),
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
    method_results = {}
    for method, prediction in predictions.items():
        radius = calibrate(y[calibration], prediction[calibration], cfg["interval_coverage"])
        method_results[method] = evaluate(y, prediction, evaluation, radius, cfg)

    common = evaluation.copy()
    for prediction in predictions.values():
        common &= np.isfinite(prediction)
    if common.sum() < 30:
        raise ValueError(f"{name}: недостаточно общих прогнозов")
    for method, prediction in predictions.items():
        method_results[method]["common_mae"] = float(np.mean(np.abs(y[common] - prediction[common])))
    return {
        "fold": name,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "calibration_start": calibration_start.isoformat(),
        "counts": counts | {"common": int(common.sum())},
        "feature_counts": {"all": len(columns), "no_pak": len(no_pak)},
        "source_rules": {key: value for key, value in rules.items() if key != "source_rules"},
        "methods": method_results,
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
        "upper_bound_recall",
        "upper_bound_false_alarm_rate",
    )
    result = {}
    for method in ("last_pak", "catboost_no_pak"):
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
    return result


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
    return "\n".join(lines)


def main() -> None:
    base_cfg = read_config()
    if pd.Timestamp(base_cfg["calibration_end"]) != DEVELOPMENT_END:
        raise ValueError("Граница разработки изменилась; протокол требует отдельного пересмотра")
    check = fixed_split_check(base_cfg)
    folds = [rolling_fold(name, start, end, base_cfg) for name, start, end in FOLDS]
    result = {
        "schema": "neftecode.forecast_rolling.baseline.v1",
        "development_end_exclusive": DEVELOPMENT_END.isoformat(),
        "fixed_split_check": check,
        "folds": folds,
        "aggregate": aggregate(folds),
    }
    with (OUT_DIR / "rolling-baseline.json").open("w") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    (OUT_DIR / "results.md").write_text(render_markdown(result), encoding="utf-8")
    print(render_markdown(result))


if __name__ == "__main__":
    main()
