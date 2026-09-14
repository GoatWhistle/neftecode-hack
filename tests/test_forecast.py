import numpy as np
import pandas as pd
import pytest

from neftecode.infrastructure.ml.forecast import calibrate, interval, metrics, run_experiment


def test_calibration_finite_sample_order_statistic():
    prediction = np.zeros(99)
    actual = np.expm1(np.arange(1, 100) / 100)
    assert calibrate(actual, prediction, .9) == pytest.approx(.9)


def test_metric_does_not_reward_perpetual_alarm_as_useful_prediction():
    lo, hi = interval(np.array([6., 12.]), 4)
    m = metrics(np.array([6., 12.]), np.array([6., 12.]), lower=lo, upper=hi)
    assert m["upper_bound_recall"] == 1
    assert m["upper_bound_false_alarm_rate"] == 1
    assert m["below_limit_fraction"] == 0


def test_metrics_use_target_units_for_near_limit_and_direction():
    actual = np.array([350., 359., 361., 370.])
    prediction = actual.copy()
    m = metrics(actual, prediction, limit=360., direction="max", near_margin=2.)
    assert m["actual_exceedances"] == 2
    assert m["mae_near_limit"] == pytest.approx(0.)
    assert m["near_margin"] == 2.
    assert m["direction"] == "max"


def test_metrics_do_not_invent_risk_without_a_target_limit():
    m = metrics(np.array([350., 370.]), np.array([351., 369.]), limit=None,
                direction="max", near_margin=None)
    assert m["mae"] == pytest.approx(1.)
    for key in ("actual_exceedances", "recall", "false_alarm_rate", "mae_near_limit"):
        assert key not in m


def test_min_direction_uses_low_bound_for_conservative_interval_alarm():
    m = metrics(np.array([48., 52.]), np.array([48., 52.]), limit=50.,
                lower=np.array([47., 51.]), upper=np.array([49., 53.]),
                direction="min", near_margin=1.)
    assert m["actual_exceedances"] == 1
    assert m["recall"] == 1.
    assert m["upper_bound_recall"] == 1.


def test_non_sulfur_experiment_does_not_inherit_sulfur_limit():
    times = pd.to_datetime(["2024-01-01", "2025-01-01", "2025-07-01", "2026-01-01"])
    decision = pd.to_datetime(np.concatenate([pd.date_range(t, periods=30, freq="D") for t in times]))
    y = np.linspace(350., 360., len(decision))
    x = pd.DataFrame({"lab.target": y, "signal": np.sin(np.arange(len(y)))}, index=range(len(y)))
    meta = pd.DataFrame({"decision_time": decision, "target_available_time": decision + pd.Timedelta(value=1, unit="h"),
                         "target_time": decision + pd.Timedelta(value=2, unit="h"), "actual_target": y})
    cfg = {"seed": 1, "train_end": "2025-01-01", "validation_end": "2025-07-01",
           "calibration_end": "2026-01-01", "interval_coverage": .9, "sulfur_limit": 10.,
           "assumptions": []}
    _, summary, _ = run_experiment(x, meta, cfg, target="actual_target")
    assert summary["limit"] is None
    assert all("actual_exceedances" not in result["test"]
               for result in summary["models"].values())
