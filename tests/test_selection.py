"""A fitted model replaces the simple baseline only on a real, useful margin."""
import numpy as np
import pytest

from neftecode.forecast import MIN_RELATIVE_GAIN, paired_bootstrap, select_model
from neftecode.quality import (MIN_ANALYSES_FOR_A_MODEL, SCENARIO_VALUE, UNKNOWN,
                               VERIFIED_FORECAST, available_estimate, classify_sources)

import pandas as pd


def errors_from(mean, n=200, spread=0.4, seed=0):
    rng = np.random.default_rng(seed)
    return np.abs(rng.normal(mean, spread, n))


def compare(baseline_mean, challenger_mean, n=200, seed=0, **kw):
    errors = {"last_pak": errors_from(baseline_mean, n, seed=seed),
              "catboost": errors_from(challenger_mean, n, seed=seed + 1)}
    scores = {k: float(v.mean()) for k, v in errors.items()}
    return select_model(scores, errors, **kw)


# --- The margin rule ---

def test_tiny_gain_keeps_the_simple_baseline():
    """The 0.3% gap observed in T05 must not switch the main model."""
    errors = {"last_pak": np.full(200, 1.3241), "catboost": np.full(200, 1.3205)}
    scores = {k: float(v.mean()) for k, v in errors.items()}
    decision = select_model(scores, errors)
    assert decision["selected"] == "last_pak"
    assert decision["relative_gain"] < MIN_RELATIVE_GAIN
    assert "меньше минимального полезного" in decision["reason"]


def test_large_and_consistent_gain_selects_the_fitted_model():
    errors = {"last_pak": np.full(200, 2.0), "catboost": np.full(200, 1.0)}
    scores = {k: float(v.mean()) for k, v in errors.items()}
    decision = select_model(scores, errors)
    assert decision["selected"] == "catboost"
    assert decision["relative_gain"] == pytest.approx(0.5)
    assert decision["bootstrap"]["ci_low"] > 0


def test_large_but_noisy_gain_still_keeps_the_baseline():
    """A gain that a paired bootstrap cannot separate from zero is not a gain."""
    rng = np.random.default_rng(7)
    baseline = np.abs(rng.normal(0, 8.0, 40))
    challenger = np.abs(rng.normal(0, 6.5, 40))
    scores = {"last_pak": float(baseline.mean()), "catboost": float(challenger.mean())}
    decision = select_model(scores, {"last_pak": baseline, "catboost": challenger})
    if decision["relative_gain"] >= MIN_RELATIVE_GAIN:
        assert decision["selected"] == "last_pak"
        assert "накрывает ноль" in decision["reason"]


def test_worse_fitted_model_never_wins():
    decision = compare(1.0, 2.0)
    assert decision["selected"] == "last_pak"


def test_the_better_of_two_simple_baselines_is_the_reference():
    errors = {"last_lab": np.full(100, 2.0), "last_pak": np.full(100, 1.5),
              "catboost": np.full(100, 1.45)}
    scores = {k: float(v.mean()) for k, v in errors.items()}
    decision = select_model(scores, errors)
    assert decision["baseline"] == "last_pak"
    assert decision["selected"] == "last_pak"


def test_selection_without_any_simple_baseline_is_refused():
    with pytest.raises(ValueError, match="простой прогноз"):
        select_model({"catboost": 1.0}, {"catboost": np.full(10, 1.0)})


def test_only_baselines_present_selects_a_baseline():
    errors = {"last_lab": np.full(50, 2.0), "last_pak": np.full(50, 1.0)}
    decision = select_model({k: float(v.mean()) for k, v in errors.items()}, errors)
    assert decision["selected"] == "last_pak"
    assert decision["challenger"] is None


def test_required_margin_is_configurable_and_respected():
    errors = {"last_pak": np.full(100, 1.0), "catboost": np.full(100, 0.9)}
    scores = {k: float(v.mean()) for k, v in errors.items()}
    assert select_model(scores, errors, min_relative_gain=0.05)["selected"] == "catboost"
    assert select_model(scores, errors, min_relative_gain=0.2)["selected"] == "last_pak"


# --- Paired comparison ---

def test_bootstrap_requires_the_same_observations_for_both_models():
    with pytest.raises(ValueError, match="одинакового набора"):
        paired_bootstrap(np.zeros(10), np.zeros(11))


def test_bootstrap_is_reproducible():
    a, b = errors_from(2.0, seed=1), errors_from(1.0, seed=2)
    assert paired_bootstrap(a, b, seed=5) == paired_bootstrap(a, b, seed=5)


def test_bootstrap_interval_brackets_the_observed_difference():
    a, b = np.full(100, 2.0), np.full(100, 1.0)
    result = paired_bootstrap(a, b)
    assert result["difference"] == pytest.approx(1.0)
    assert result["ci_low"] <= 1.0 <= result["ci_high"]


# --- What may be estimated at all ---

def series(n):
    return pd.DataFrame({"time": pd.date_range("2023-01-01", periods=n, freq="1D"),
                         "value": np.linspace(1, 2, n)})


def test_property_with_many_analyses_gets_a_forecast():
    sources = classify_sources({"sulfur_mgkg": series(1462)})
    assert sources["sulfur_mgkg"].method == VERIFIED_FORECAST
    assert sources["sulfur_mgkg"].has_model is True


def test_cetane_number_with_42_analyses_is_never_promised_a_model():
    sources = classify_sources({"cetane_number": series(42)})
    assert sources["cetane_number"].method == UNKNOWN
    assert sources["cetane_number"].has_model is False
    assert "42" in sources["cetane_number"].reason


def test_threshold_for_claiming_a_model_is_explicit():
    assert classify_sources({"q": series(MIN_ANALYSES_FOR_A_MODEL)})["q"].has_model is True
    assert classify_sources({"q": series(MIN_ANALYSES_FOR_A_MODEL - 1)})["q"].has_model is False


def test_estimate_without_model_and_without_scenario_value_is_unknown():
    sources = classify_sources({"cetane_number": series(42)})
    estimate = available_estimate("cetane_number", sources)
    assert estimate["method"] == UNKNOWN
    assert estimate["value"] is None


def test_scenario_value_is_labelled_as_scenario_not_as_measurement():
    sources = classify_sources({"cetane_number": series(42)})
    estimate = available_estimate("cetane_number", sources, scenario_value=51.0)
    assert estimate["method"] == SCENARIO_VALUE
    assert estimate["value"] == 51.0
    assert "не является измерением" in estimate["note"]


def test_scenario_value_cannot_override_a_verified_forecast():
    sources = classify_sources({"sulfur_mgkg": series(1462)})
    estimate = available_estimate("sulfur_mgkg", sources, scenario_value=1.0)
    assert estimate["method"] == VERIFIED_FORECAST


def test_unknown_property_carries_the_blocking_note():
    sources = classify_sources({"cetane_number": series(42)})
    assert any("блокирует план" in note for note in sources["cetane_number"].limitations)
