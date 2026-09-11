"""Availability, horizons and model validity: nothing from the future may reach a past decision."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from neftecode.data import (CASE_MAX_HORIZON_HOURS, CASE_MAX_LAB_DELAY_HOURS, backward_readings,
                            build_features, check_time_assumptions, make_dataset, series_frame,
                            split_periods)

CFG = {"horizon_hours": 2, "lab_delay_hours": 4, "history_window_hours": 6,
       "lab_max_age_hours": 48, "pak_max_age_minutes": 30}


def synthetic(hours=48):
    times = pd.date_range("2026-01-01", periods=hours * 6, freq="10min")
    signals = pd.DataFrame({"avt.T1": np.linspace(100, 120, len(times)),
                            "ht.P3": -np.linspace(1, 2, len(times))}, index=times)
    online = pd.DataFrame({"time": times, "value": 5 + np.arange(len(times)) / 1000})
    lab = series_frame([(t.isoformat(), 6.0 + i * 0.1)
                        for i, t in enumerate(times[::72])], "test")
    return signals, lab, online


# --- Confirmed case bounds are enforced, not merely documented ---

def test_shipped_config_matches_the_confirmed_case_bounds():
    cfg = json.loads(Path("config/experiment.json").read_text())
    bounds = check_time_assumptions(cfg)
    assert 0 < bounds["horizon_hours"] <= CASE_MAX_HORIZON_HOURS
    assert bounds["lab_delay_hours"] == CASE_MAX_LAB_DELAY_HOURS
    assert bounds["history_window_hours"] > 0


@pytest.mark.parametrize("horizon", [0, -1, 3.5, 6, None, float("nan")])
def test_horizon_outside_the_case_range_is_refused(horizon):
    with pytest.raises(ValueError, match="горизонт прогноза"):
        check_time_assumptions({**CFG, "horizon_hours": horizon})


def test_lab_delay_longer_than_the_expert_bound_is_refused():
    with pytest.raises(ValueError, match="больше названного экспертом"):
        check_time_assumptions({**CFG, "lab_delay_hours": 6})


def test_history_window_is_a_separate_quantity_from_the_horizon():
    """The 6-hour feature window is backward-looking history, not a 6-hour forecast."""
    bounds = check_time_assumptions(CFG)
    assert bounds["history_window_hours"] != bounds["horizon_hours"]
    with pytest.raises(ValueError, match="окно прошлых признаков"):
        check_time_assumptions({**CFG, "history_window_hours": 0})


def test_feature_names_state_the_window_they_come_from():
    signals, lab, online = synthetic()
    x, _ = build_features(signals, lab, online, [signals.index[-1]], CFG)
    assert "avt.T1.mean6h" in x.columns and "avt.T1.delta6h" in x.columns
    wider = build_features(signals, lab, online, [signals.index[-1]], {**CFG, "history_window_hours": 12})[0]
    assert "avt.T1.mean12h" in wider.columns, "имя признака обязано называть своё окно"


# --- Availability ---

def test_sample_taken_but_not_released_stays_unknown():
    lab = series_frame([("2026-01-01 08:00", 5.0)], "test")
    joined = backward_readings(pd.to_datetime(["2026-01-01 11:59", "2026-01-01 12:00"]), lab, 4)
    assert pd.isna(joined.value.iloc[0]), "проба не может быть видна раньше своей готовности"
    assert joined.value.iloc[1] == 5.0


def test_late_sample_never_appears_retroactively():
    """A result released later must not change what was decidable earlier."""
    signals, lab, online = synthetic()
    decisions = pd.to_datetime(["2026-01-01 12:00", "2026-01-01 20:00"])
    before = build_features(signals, lab, online, decisions, CFG)[1]
    slower = build_features(signals, lab, online, decisions, {**CFG, "lab_delay_hours": 4})[1]
    pd.testing.assert_frame_equal(before, slower)
    faster = build_features(signals, lab, online, decisions, {**CFG, "lab_delay_hours": 0})[1]
    assert (faster.lab_age_hours.fillna(1e9) <= before.lab_age_hours.fillna(1e9)).all(), \
        "меньшая задержка может только приблизить доступность, но не отодвинуть её"


def test_availability_times_are_kept_for_both_sources():
    signals, lab, online = synthetic()
    _, meta = build_features(signals, lab, online, [pd.Timestamp("2026-01-02 00:00")], CFG)
    for column in ("lab_sample_time", "lab_available_time", "pak_sample_time", "pak_available_time"):
        assert column in meta.columns, f"утрачено время {column}"
    row = meta.iloc[0]
    assert row.lab_available_time >= row.lab_sample_time
    assert row.lab_available_time <= row.decision_time


def test_pak_and_lab_keep_independent_time_axes():
    """The two sources are joined by time, never by row number."""
    times = pd.date_range("2026-01-01", periods=300, freq="10min")
    signals = pd.DataFrame({"avt.T1": np.arange(len(times), dtype=float)}, index=times)
    online = pd.DataFrame({"time": times[::3], "value": np.linspace(5, 6, len(times[::3]))})
    lab = series_frame([("2026-01-01 02:00", 7.0), ("2026-01-01 20:00", 9.0)], "test")
    _, meta = build_features(signals, lab, online, [pd.Timestamp("2026-01-02 00:00")], CFG)
    row = meta.iloc[0]
    assert row.lab_sample_time == pd.Timestamp("2026-01-01 20:00")
    assert row.pak_sample_time != row.lab_sample_time
    assert row.pak_sample_time <= row.decision_time


# --- One analysis is one evaluation row ---

def test_each_analysis_yields_exactly_one_row():
    signals, lab, online = synthetic(hours=72)
    x, meta = make_dataset(signals, lab, online, CFG)
    assert len(x) == len(meta)
    assert len(meta) <= len(lab), "анализы не должны размножаться на сетку телеметрии"
    assert meta.target_time.is_unique
    assert meta.decision_time.is_unique


def test_duplicated_target_times_are_refused():
    signals, lab, online = synthetic(hours=72)
    doubled = pd.concat([lab, lab.iloc[[1]]], ignore_index=True).sort_values("time").reset_index(drop=True)
    with pytest.raises(ValueError, match="повторяющееся время отбора"):
        make_dataset(signals, doubled, online, CFG)


def test_target_sample_cannot_enter_its_own_features():
    signals, lab, online = synthetic(hours=72)
    _, meta = make_dataset(signals, lab, online, CFG)
    known = meta.dropna(subset=["lab_sample_time"])
    assert (known.lab_sample_time < known.target_time).all(), "проба цели попала в признаки"
    assert (known.lab_available_time <= known.decision_time).all()


def test_target_availability_uses_the_declared_delay():
    signals, lab, online = synthetic(hours=72)
    _, meta = make_dataset(signals, lab, online, CFG)
    delta = (meta.target_available_time - meta.target_time).dt.total_seconds() / 3600
    assert (delta == CFG["lab_delay_hours"]).all()


# --- Split boundaries and model validity ---

def test_splits_stay_disjoint_and_purge_unavailable_boundary_targets():
    meta = pd.DataFrame({
        "decision_time": pd.to_datetime(["2024-12-31 22:00", "2025-01-01 00:00", "2025-07-01 00:00",
                                         "2026-01-01 00:00"]),
        "target_available_time": pd.to_datetime(["2025-01-01 02:00", "2025-01-01 06:00",
                                                 "2025-07-01 06:00", "2026-01-01 06:00"])})
    masks = split_periods(meta, {"train_end": "2025-01-01", "validation_end": "2025-07-01",
                                 "calibration_end": "2026-01-01"})
    stacked = np.stack(list(masks.values()))
    assert stacked.sum(axis=0).max() == 1, "периоды пересекаются"
    assert not stacked[:, 0].any(), "цель на границе, ставшая известной уже в следующем периоде, не покидает purge"
    assert masks["test"][3]


def test_split_boundaries_must_increase():
    meta = pd.DataFrame({"decision_time": pd.to_datetime(["2025-01-01"]),
                         "target_available_time": pd.to_datetime(["2025-01-01"])})
    with pytest.raises(ValueError, match="по возрастанию"):
        split_periods(meta, {"train_end": "2026-01-01", "validation_end": "2025-07-01",
                             "calibration_end": "2026-01-01"})


def test_model_is_not_usable_before_its_calibration_period_ended():
    from neftecode.runtime import validate_origin
    bundle = {"config": {"calibration_end": "2026-01-01"}}
    with pytest.raises(ValueError, match="утечк"):
        validate_origin("2025-12-31T23:00:00", bundle)
    assert validate_origin("2026-01-02T00:00:00", bundle) == pd.Timestamp("2026-01-02T00:00:00")


def test_origin_with_timezone_is_refused_since_sources_share_one_local_clock():
    from neftecode.runtime import validate_origin
    with pytest.raises(ValueError, match="часового пояса"):
        validate_origin("2026-01-02T00:00:00+03:00", {"config": {"calibration_end": "2026-01-01"}})


# --- Reproducibility of the conversion itself ---

def test_features_are_reproducible_for_the_same_inputs():
    signals, lab, online = synthetic()
    decisions = pd.to_datetime(["2026-01-01 12:00", "2026-01-02 00:00"])
    first = build_features(signals, lab, online, decisions, CFG)
    second = build_features(signals, lab, online, decisions, CFG)
    pd.testing.assert_frame_equal(first[0], second[0])
    pd.testing.assert_frame_equal(first[1], second[1])


def test_negative_process_values_are_not_silently_dropped():
    signals, lab, online = synthetic()
    x, _ = build_features(signals, lab, online, [signals.index[-1]], CFG)
    assert x["ht.P3.now"].iloc[0] < 0, "отрицательное значение процесса не является автоматической ошибкой"
