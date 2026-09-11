import numpy as np
import pytest

from neftecode.forecast import calibrate, interval, metrics


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
