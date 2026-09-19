import numpy as np
import pandas as pd
import pytest

from neftecode.infrastructure.data.data import backward_readings, build_features, series_frame, split_periods


CFG = {"horizon_hours": 2, "lab_delay_hours": 4, "history_window_hours": 6,
       "lab_max_age_hours": 48, "pak_max_age_minutes": 30}


def test_lab_only_available_after_release_delay():
    lab = series_frame([("2026-01-01 08:00", 5), ("2026-01-01 10:00", 100)], "test")
    joined = backward_readings(pd.to_datetime(["2026-01-01 11:59", "2026-01-01 12:00", "2026-01-01 14:00"]), lab, 4)
    assert pd.isna(joined.value.iloc[0])
    assert joined.value.iloc[1:].tolist() == [5, 100]
    assert (joined.dropna().available_time <= joined.dropna().decision_time).all()


def test_future_mutation_cannot_change_features_or_trust():
    times = pd.date_range("2026-01-01", periods=217, freq="10min")
    signals = pd.DataFrame({"avt.T1": np.arange(len(times)), "ht.P3": -np.arange(len(times))}, index=times)
    online = pd.DataFrame({"time": times, "value": 5 + np.arange(len(times)) / 1000})
    lab = series_frame([("2026-01-01 01:00", 5), ("2026-01-01 08:00", 7), ("2026-01-02 01:00", 10)], "test")
    decisions = pd.to_datetime(["2026-01-01 07:00", "2026-01-01 12:00"])
    x1, m1 = build_features(signals, lab, online, decisions, CFG)
    signals.loc[signals.index > decisions.max()] = 999999
    online.loc[online.time > decisions.max(), "value"] = 999999
    lab.loc[lab.time + pd.Timedelta(value=4, unit="h") > decisions.max(), "value"] = 999999
    x2, m2 = build_features(signals, lab, online, decisions, CFG)
    pd.testing.assert_frame_equal(x1, x2)
    pd.testing.assert_frame_equal(m1, m2)
    assert x1["ht.P3.now"].lt(0).all()


def test_frozen_analyzer_is_masked_not_replaced_with_zero():
    times = pd.date_range("2026-01-01", periods=73, freq="10min")
    signals = pd.DataFrame({"avt.T1": range(73)}, index=times)
    online = pd.DataFrame({"time": times, "value": 7.0})
    lab = series_frame([("2026-01-01 01:00", 7)], "test")
    x, meta = build_features(signals, lab, online, [times[-1]], CFG)
    assert meta.pak_frozen.iloc[0]
    assert not meta.pak_usable.iloc[0]
    assert np.isnan(x["pak.sulfur"].iloc[0])
    assert x["lab.sulfur"].iloc[0] == 7


def test_conflicting_duplicates_fail_explicitly():
    with pytest.raises(ValueError, match="дубликаты"):
        series_frame([("2026-01-01", 5), ("2026-01-01", 6)], "test")


def test_negative_release_delay_cannot_expose_future_results():
    with pytest.raises(ValueError, match="Задержка"):
        backward_readings(pd.to_datetime(["2026-01-01"]), series_frame([("2026-01-02", 7)], "test"), -24)


def test_calendar_splits_purge_unavailable_boundary_targets():
    meta = pd.DataFrame({"decision_time": pd.to_datetime(["2024-12-31 20:00", "2025-01-01 00:00", "2026-01-01 00:00"]),
                         "target_available_time": pd.to_datetime(["2025-01-01 04:00", "2025-01-01 08:00", "2026-01-01 08:00"])})
    masks = split_periods(meta, {"train_end": "2025-01-01", "validation_end": "2025-07-01", "calibration_end": "2026-01-01"})
    assert not any(m[0] for m in masks.values())
    assert masks["validation"][1]
    assert masks["test"][2]
    assert np.stack(list(masks.values())).sum(axis=0).max() == 1
