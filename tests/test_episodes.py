"""Episode duration and alarm accounting: one convention, no double credit, unknown preserved."""
import numpy as np
import pandas as pd
import pytest

from neftecode.infrastructure.ml.batch import (DURATION_RULE, classify_episodes, excursion_episodes,
                             sampling_step_hours, violation_profile)
from neftecode.infrastructure.ml.margin import alarm_events, lead_times

STEP = pd.Timedelta(minutes=10)


def series(values, start="2026-01-01"):
    index = pd.date_range(start, periods=len(values), freq="10min")
    return pd.Series(np.asarray(values, float), index=index)


# --- One duration convention for episodes of any length ---

def test_single_reading_occupies_one_sampling_interval():
    episodes = excursion_episodes(series([5, 12, 5, 5, 5, 5]), limit=10)
    assert len(episodes) == 1
    assert episodes.duration_hours.iloc[0] == pytest.approx(10 / 60)


def test_run_duration_counts_every_reading_not_only_the_span():
    """Six readings above the limit last six intervals, not five."""
    episodes = excursion_episodes(series([5, 12, 12, 12, 12, 12, 12, 5]), limit=10)
    assert episodes.n_points.iloc[0] == 6
    assert episodes.duration_hours.iloc[0] == pytest.approx(60 / 60)
    assert episodes.span_hours.iloc[0] == pytest.approx(50 / 60)


def test_duration_is_proportional_to_the_number_of_readings():
    short = excursion_episodes(series([5, 12, 5]), limit=10).duration_hours.iloc[0]
    long = excursion_episodes(series([5, 12, 12, 12, 12, 5]), limit=10).duration_hours.iloc[0]
    assert long == pytest.approx(4 * short), "короткий и длинный эпизод считаются одним правилом"


def test_gap_in_the_record_ends_the_episode():
    a = series([12, 12], start="2026-01-01 00:00")
    b = series([12, 12], start="2026-01-01 06:00")
    episodes = excursion_episodes(pd.concat([a, b]), limit=10)
    assert len(episodes) == 2


def test_profile_states_the_duration_rule_it_used():
    profile = violation_profile(series([5, 12, 12, 5] * 30), limit=10)
    assert profile["duration_rule"] == DURATION_RULE
    assert profile["episodes"] == 30


def test_classification_uses_the_same_durations():
    readings = series([5] + [12] * 30 + [5] + [12] * 3 + [5])
    episodes = classify_episodes(excursion_episodes(readings, 10), sustained_hours=4)
    assert set(episodes.kind) == {"sustained", "flicker"}
    assert episodes.loc[episodes.kind == "sustained", "duration_hours"].iloc[0] == pytest.approx(5.0)


def test_sampling_step_of_a_single_reading_is_zero_not_a_guess():
    assert sampling_step_hours(series([5])) == 0.0


# --- Alarm readings are not alarm notifications ---

def test_a_continuous_flag_is_one_alarm_event():
    stamps = pd.date_range("2026-01-01 00:00", periods=36, freq="10min")
    assert len(alarm_events(stamps, rearm_hours=1.0)) == 1


def test_separate_alarms_after_the_rearm_gap_are_counted_separately():
    stamps = pd.DatetimeIndex(list(pd.date_range("2026-01-01 00:00", periods=6, freq="10min"))
                              + list(pd.date_range("2026-01-01 04:00", periods=6, freq="10min")))
    assert len(alarm_events(stamps, rearm_hours=1.0)) == 2


def test_empty_alarm_record_gives_no_events():
    assert len(alarm_events(pd.DatetimeIndex([]))) == 0


# --- Lead time: early, late, missed and unknown stay apart ---

def episode_readings(start="2026-01-01 12:00", length=30, lead_in=72):
    before = series([5.0] * lead_in, start="2026-01-01 00:00")
    during = series([12.0] * length, start=start)
    after = series([5.0] * 12, start=pd.Timestamp(start) + length * STEP)
    return pd.concat([before, during, after])


def test_alarm_before_the_episode_is_early_and_carries_a_lead_time():
    readings = episode_readings()
    alarms = pd.date_range("2026-01-01 10:00", periods=3, freq="10min")
    result = lead_times(readings, alarms, limit=10, sustained_hours=4, max_lead_hours=24)
    assert result["episodes"] == 1
    assert result["early"] == 1 and result["late"] == 0 and result["missed"] == 0
    assert result["median_lead_hours"] == pytest.approx(2.0)


def test_alarm_inside_the_episode_is_late_and_contributes_no_lead_time():
    readings = episode_readings()
    alarms = pd.date_range("2026-01-01 13:00", periods=3, freq="10min")
    result = lead_times(readings, alarms, limit=10, sustained_hours=4, max_lead_hours=24)
    assert result["late"] == 1 and result["early"] == 0
    assert result["median_lead_hours"] is None, "поздний сигнал не должен улучшать упреждение"
    assert result["per_episode"][0]["late_by_hours"] == pytest.approx(1.0)


def test_no_alarm_in_the_window_is_a_miss():
    readings = episode_readings()
    alarms = pd.date_range("2025-12-30 00:00", periods=2, freq="10min")
    result = lead_times(readings, alarms, limit=10, sustained_hours=4, max_lead_hours=1)
    assert result["missed"] + result["unknown"] == 1
    assert result["early"] == 0


def test_episode_outside_the_alarm_record_is_unknown_not_missed():
    """Absence of an alarm record is absence of knowledge, not absence of risk."""
    readings = episode_readings(start="2026-06-01 12:00")
    alarms = pd.date_range("2026-01-01 00:00", periods=3, freq="10min")
    result = lead_times(readings, alarms, limit=10, sustained_hours=4, max_lead_hours=24,
                        alarm_period=("2026-01-01 00:00", "2026-01-02 00:00"))
    assert result["unknown"] == 1
    assert result["missed"] == 0


def test_without_a_declared_alarm_period_nothing_is_unknown():
    readings = episode_readings()
    result = lead_times(readings, pd.DatetimeIndex([]), limit=10, sustained_hours=4)
    assert result["unknown"] == 0
    assert result["missed"] == 1


def test_one_alarm_event_cannot_be_credited_to_two_episodes():
    first = series([12.0] * 30, start="2026-01-01 12:00")
    quiet = series([5.0] * 30, start="2026-01-01 17:00")
    second = series([12.0] * 30, start="2026-01-01 22:00")
    lead_in = series([5.0] * 72, start="2026-01-01 00:00")
    readings = pd.concat([lead_in, first, quiet, second])
    alarms = pd.date_range("2026-01-01 10:00", periods=2, freq="10min")
    result = lead_times(readings, alarms, limit=10, sustained_hours=4, max_lead_hours=24)
    assert result["episodes"] == 2
    assert result["early"] == 1, "одно событие тревоги не может засчитаться двум эпизодам"
    assert result["missed"] == 1


def test_alarm_burden_is_reported_next_to_lead_time():
    readings = episode_readings()
    alarms = pd.date_range("2026-01-01 00:00", periods=200, freq="10min")
    result = lead_times(readings, alarms, limit=10, sustained_hours=4, max_lead_hours=24,
                        total_readings=len(readings))
    assert result["alarm_readings"] == 200
    assert result["alarm_events"] == 1, "непрерывный флаг — одно уведомление"
    assert result["alarm_reading_share_of_record"] is not None
    assert result["alarm_events_per_early_episode"] is not None


def test_readings_and_events_are_reported_as_different_numbers():
    readings = episode_readings()
    alarms = pd.date_range("2026-01-01 09:00", periods=12, freq="10min")
    result = lead_times(readings, alarms, limit=10, sustained_hours=4, max_lead_hours=24)
    assert result["alarm_readings"] == 12
    assert result["alarm_events"] == 1
    assert result["alarm_readings"] != result["alarm_events"]


def test_scope_states_the_matching_window_is_not_a_forecast_horizon():
    result = lead_times(episode_readings(), pd.date_range("2026-01-01 10:00", periods=2, freq="10min"),
                        limit=10, sustained_hours=4, max_lead_hours=24)
    assert "не горизонт прогноза" in result["scope"]
    assert "не равно числу" in result["scope"]


def test_no_sustained_episode_yields_an_empty_but_valid_result():
    readings = series([5.0] * 50 + [12.0] * 3 + [5.0] * 20)
    result = lead_times(readings, pd.DatetimeIndex([]), limit=10, sustained_hours=4)
    assert result["episodes"] == 0
    assert result["median_lead_hours"] is None
