"""Causality checks for the pre-registered sulfur forecast research harness."""
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd


SCRIPT = Path(__file__).parents[1] / "context/forecast-research/rolling.py"
SPEC = importlib.util.spec_from_file_location("forecast_research_rolling", SCRIPT)
rolling = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(rolling)


def test_bias_correction_ignores_future_lab_results():
    available = pd.date_range("2025-01-01", periods=8, freq="h")
    pairs = pd.DataFrame(
        {
            "sample_time": available,
            "available_time": available,
            "bias": [1, 2, 3, 4, 5, 100, 200, 300],
        }
    )
    at = pd.Timestamp("2025-01-01 04:30")
    past_only = pairs.loc[pairs.available_time <= at]

    with_future = rolling.causal_bias_correction([at], pairs, window=5)[0]
    without_future = rolling.causal_bias_correction([at], past_only, window=5)[0]

    assert with_future == without_future == 3.0


def test_bias_correction_is_zero_until_five_pairs_are_available():
    available = pd.date_range("2025-01-01", periods=5, freq="h")
    pairs = pd.DataFrame(
        {
            "sample_time": available,
            "available_time": available,
            "bias": np.arange(1, 6, dtype=float),
        }
    )

    values = rolling.causal_bias_correction(
        [pd.Timestamp("2025-01-01 03:30"), pd.Timestamp("2025-01-01 04:00")],
        pairs,
        window=5,
    )

    assert values.tolist() == [0.0, 3.0]


def test_residual_prediction_uses_no_pak_fallback_only_when_needed():
    last_pak = np.array([4.0, np.nan, 9.0])
    residual = np.array([0.0, 100.0, np.log(1.1)])
    fallback = np.array([40.0, 6.5, 90.0])

    prediction = rolling.combine_residual_prediction(last_pak, residual, fallback)

    assert np.isclose(prediction[0], 4.0)
    assert prediction[1] == 6.5
    assert np.isclose(prediction[2], np.expm1(np.log1p(9.0) + np.log(1.1)))


def synthetic_aci_series(seed=7, evaluation_size=1000):
    rng = np.random.default_rng(seed)
    calibration_size = 100
    size = calibration_size + evaluation_size
    decisions = pd.date_range("2024-12-27 20:00", periods=size, freq="h").as_unit("ns")
    meta = pd.DataFrame(
        {
            "decision_time": decisions,
            "target_available_time": decisions + np.timedelta64(30, "m"),
        }
    )
    point = np.full(size, 5.0)
    residuals = np.r_[
        rng.normal(0.0, 0.08, calibration_size),
        rng.normal(0.16, 0.08, evaluation_size),
    ]
    actual = np.expm1(np.log1p(point) + residuals)
    calibration = np.zeros(size, dtype=bool)
    calibration[:calibration_size] = True
    return meta, actual, point, calibration, ~calibration


def test_aci_does_not_use_an_outcome_before_it_is_available():
    meta, actual, point, calibration, evaluation = synthetic_aci_series(evaluation_size=80)
    evaluation_rows = np.flatnonzero(evaluation)
    meta.loc[evaluation, "target_available_time"] = (
        pd.DatetimeIndex(meta.loc[evaluation, "decision_time"]).as_unit("ns") + np.timedelta64(6, "h")
    )
    original = rolling.adaptive_upper_bounds(meta, actual, point, calibration, evaluation, gamma=0.01)
    changed = actual.copy()
    changed_row = evaluation_rows[10]
    changed[changed_row] *= 100
    with_future_changed = rolling.adaptive_upper_bounds(
        meta, changed, point, calibration, evaluation, gamma=0.01
    )
    before_available = (
        evaluation
        & (meta.decision_time < meta.target_available_time.iloc[changed_row])
    )

    assert np.allclose(
        original["upper"][before_available],
        with_future_changed["upper"][before_available],
        equal_nan=True,
    )


def test_aci_returns_near_target_after_a_level_shift():
    meta, actual, point, calibration, evaluation = synthetic_aci_series()
    state = rolling.adaptive_upper_bounds(meta, actual, point, calibration, evaluation, gamma=0.01)
    errors = (actual[evaluation] > state["upper"][evaluation]).astype(float)

    assert 0.035 <= errors[-500:].mean() <= 0.065
