import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from neftecode.infrastructure.data.data import validate_forecast_selection
from neftecode.infrastructure.ml.forecast import calibrate, interval, metrics, predict_candidate, run_experiment


def test_shipped_forecast_selection_is_the_frozen_pre2026_evidence():
    cfg = json.loads(Path("config/experiment.json").read_text())
    frozen = json.loads(Path("context/forecast-research/selection.json").read_text())
    selection = validate_forecast_selection(cfg)
    for key in ("selected_before_2026", "selected", "baseline", "bias_window_pairs",
                "min_pairs", "development_end", "evidence", "evidence_sha256"):
        assert selection[key] == frozen[key]
    assert hashlib.sha256(Path(selection["evidence"]).read_bytes()).hexdigest() == selection["evidence_sha256"]


def test_frozen_forecast_selection_refuses_parameter_drift():
    cfg = json.loads(Path("config/experiment.json").read_text())
    cfg["forecast_selection"]["bias_window_pairs"] = 40
    with pytest.raises(ValueError, match="замороженным протоколом"):
        validate_forecast_selection(cfg)


def test_bias_corrected_pak_candidate_applies_the_causal_feature_and_zero_floor():
    x = pd.DataFrame({"pak.sulfur": [5.0, 0.2, np.nan],
                      "pak.lab_bias20": [0.7, -1.0, 4.0]})
    prediction = predict_candidate({}, "last_pak_bc", x)
    assert prediction[:2].tolist() == pytest.approx([5.7, 0.0])
    assert np.isnan(prediction[2])


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


def test_preregistered_rolling_choice_does_not_rewrite_validation_audit():
    starts = pd.to_datetime(["2024-01-01", "2025-01-01", "2025-07-01", "2026-01-01"])
    decision = pd.DatetimeIndex(pd.to_datetime(
        np.concatenate([pd.date_range(t, periods=30, freq="D") for t in starts])
    )).as_unit("ns")
    y = 5.0 + np.sin(np.arange(len(decision)) / 9)
    x = pd.DataFrame({
        "lab.sulfur": y + 0.5,
        "pak.sulfur": y,
        "pak.lab_bias20": np.full(len(y), 2.0),
        "signal": np.cos(np.arange(len(y)) / 7),
    })
    meta = pd.DataFrame({
        "decision_time": decision,
        "target_available_time": decision + np.timedelta64(1, "h"),
        "target_time": decision + np.timedelta64(2, "h"),
        "actual_sulfur": y,
    })
    cfg = {
        "seed": 1, "train_end": "2025-01-01", "validation_end": "2025-07-01",
        "calibration_end": "2026-01-01", "interval_coverage": 0.9,
        "sulfur_limit": 10.0, "assumptions": [],
        "forecast_selection": {
            "method": "preregistered_rolling_v1", "selected_before_2026": True,
            "selected": "last_pak_bc", "baseline": "last_pak",
            "bias_window_pairs": 20, "min_pairs": 5, "development_end": "2026-01-01",
            "evidence": "context/forecast-research/rolling-f4.json",
            "evidence_sha256": "ef83c7a0d8f8513886c9934c98ce08e2606df34c6715bd7908c545f3b2c1f627",
        },
    }
    bundle, summary, _ = run_experiment(x, meta, cfg)
    assert summary["selection_decision"]["selected"] == "last_pak"
    assert summary["selected"] == bundle["selected"] == "last_pak_bc"
