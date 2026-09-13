import numpy as np
import pandas as pd
import pytest

import neftecode.infrastructure.ml.risk as risk
from neftecode.infrastructure.ml.risk import detection_metrics, select_threshold


def test_select_threshold_uses_full_false_alarm_budget_for_distinct_scores():
    labels = np.array([False, False, False, False, True, True])
    scores = np.array([0.1, 0.2, 0.3, 0.4, 0.25, 0.9])

    threshold = select_threshold(labels, scores, false_alarm_budget=0.5)

    # Two of four negatives may alarm. The open interval above 0.2 also
    # retains a positive score at 0.25 instead of losing it at 0.3.
    assert (scores[~labels] >= threshold).sum() == 2
    assert scores[4] >= threshold


def test_select_threshold_does_not_split_equal_score_ties():
    labels = np.array([False, False, False, False, True])
    scores = np.array([0.9, 0.9, 0.2, 0.1, 1.0])

    threshold = select_threshold(labels, scores, false_alarm_budget=0.25)

    # One false alarm is allowed mathematically, but the tied 0.9 group
    # cannot be split, so both tied negatives must stay below threshold.
    assert threshold > 0.9
    assert (scores[~labels] >= threshold).sum() == 0


def test_select_threshold_requires_a_finite_negative_score():
    with pytest.raises(ValueError, match="Нет проб без превышения"):
        select_threshold([True, True], [0.1, np.nan], false_alarm_budget=0)


def test_detection_metrics_excludes_unavailable_scores_and_counts_hidden_events():
    metrics = detection_metrics(
        labels=[False, True, True, False],
        scores=[0.1, np.nan, 0.9, np.nan],
        threshold=0.5,
    )

    assert metrics["n"] == 4
    assert metrics["scored"] == 2
    assert metrics["unavailable"] == 2
    assert metrics["exceedances_without_score"] == 1
    assert metrics["tp"] == 1
    assert metrics["fp"] == 0
    assert metrics["fn"] == 0
    assert metrics["tn"] == 1
    assert metrics["recall"] == 1
    assert metrics["false_alarm_rate"] == 0


def test_model_and_thresholds_do_not_depend_on_test_period(monkeypatch):
    class FakeModel:
        def fit(self, x, y):
            return self

        def predict_proba(self, x):
            score = x.iloc[:, 0].to_numpy(float)
            return np.column_stack([1 - score, score])

    masks = {
        "train": np.array([1] * 4 + [0] * 40, dtype=bool),
        "validation": np.array([0] * 4 + [1] * 32 + [0] * 8, dtype=bool),
        "calibration": np.array([0] * 36 + [1] * 4 + [0] * 4, dtype=bool),
        "test": np.array([0] * 40 + [1] * 4, dtype=bool),
    }
    monkeypatch.setattr(risk, "split_periods", lambda meta, cfg: masks)
    monkeypatch.setattr(risk, "CatBoostClassifier", lambda **kwargs: FakeModel())
    monkeypatch.setattr(risk, "make_pipeline", lambda *args: FakeModel())

    labels = np.array([False, True] * 22)
    x = pd.DataFrame({
        "feature": np.tile([0.2, 0.8], 22),
        "pak.sulfur": np.tile([0.1, 0.9], 22),
        "lab.sulfur": np.tile([0.3, 0.7], 22),
    })
    meta = pd.DataFrame({
        "decision_time": pd.date_range("2026-01-01", periods=44, freq="h"),
        "target_available_time": pd.date_range("2026-01-01", periods=44, freq="h"),
        "actual_sulfur": np.where(labels, 11.0, 5.0),
    })
    cfg = {"sulfur_limit": 10, "risk_false_alarm_budget": 0.5, "seed": 1}

    first_bundle, _, _ = risk.run_risk_experiment(x, meta, cfg)
    x_changed, meta_changed = x.copy(), meta.copy()
    x_changed.loc[40:, ["feature", "pak.sulfur", "lab.sulfur"]] = 0.99
    meta_changed.loc[40:, "actual_sulfur"] = 5.0
    second_bundle, _, _ = risk.run_risk_experiment(x_changed, meta_changed, cfg)

    assert second_bundle["selected"] == first_bundle["selected"]
    assert second_bundle["fallback"] == first_bundle["fallback"]
    assert second_bundle["thresholds"] == first_bundle["thresholds"]
