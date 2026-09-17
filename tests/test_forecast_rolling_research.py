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
