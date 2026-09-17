"""Stub values and source-trust thresholds: removed and derived from history, not hand-set."""
import numpy as np
import pandas as pd
import pytest

from neftecode.application.services.trust import DataTrustAgent
from neftecode.infrastructure.data.data import (STUB_VALUE, _untrusted_runs, conflict_mask, derive_source_rules,
                                                frozen_rule, mask_stubs)


def test_stub_values_become_missing_and_dead_columns_are_dropped():
    frame = pd.DataFrame({"a": [1.0, STUB_VALUE, 3.0, 4.0], "dead": [STUB_VALUE] * 4, "b": [307.5, 2.0, 2.0, 2.0]})
    masked, dead = mask_stubs(frame)
    assert dead == ["dead"] and list(masked.columns) == ["a", "b"]
    assert np.isnan(masked.loc[1, "a"]) and masked.loc[0, "b"] == 307.5


def history(days=60, seed=0):
    rng = np.random.default_rng(seed)
    times = pd.date_range("2024-01-01", periods=days * 144, freq="10min")
    pak = pd.DataFrame({"time": times, "value": 8 + rng.normal(0, 1, len(times)).round(4)})
    pak.loc[1000:1011, "value"] = 12.3456  # one frozen run of 12 readings
    lab_times = pd.date_range("2024-01-01 08:00", periods=days, freq="24h")
    lab_values = pak.set_index("time").value.reindex(lab_times).to_numpy() + rng.normal(0, 1, days)
    lab = pd.DataFrame({"time": lab_times, "value": np.abs(lab_values)})
    signals = pd.DataFrame(rng.normal(size=(len(times), 20)), index=times)
    signals.iloc[::50, :1] = np.nan                     # ordinary single gaps
    signals.iloc[7::97, :12] = np.nan                   # simultaneous polling failures
    return signals, lab, pak


def test_rules_are_derived_from_the_history_with_the_method_recorded():
    signals, lab, pak = history()
    rules = derive_source_rules(signals, lab, pak, "2024-03-01", {})
    assert rules["lab_max_age_hours"] == 48.0
    assert rules["pak_max_age_minutes"] == 30.0 and rules["pak_period_minutes"] == 10.0
    assert rules["pak_frozen_readings"] == 2      # a live analyser never repeats a value here
    assert 1.0 < rules["pak_conflict_mgkg"] < 3.0
    assert rules["telemetry_max_missing_fraction"] < 12 / 20   # the burst of 12 missing sensors is an outage
    assert rules["telemetry_max_missing_fraction"] >= 1 / 20   # a single missing sensor is normal
    assert rules["source_rules"]["method"]["conflict_quantile"] == 0.95


def test_rules_use_only_the_period_before_the_cut():
    signals, lab, pak = history()
    early = derive_source_rules(signals, lab, pak, "2024-02-01", {})
    assert early["source_rules"]["observed"]["lab_samples"] == 31


def test_rules_refuse_too_little_history():
    signals, lab, pak = history(days=5)
    with pytest.raises(ValueError):
        derive_source_rules(signals, lab.iloc[:3], pak, "2024-01-05", {})


def test_frozen_and_conflict_rules_follow_the_configuration():
    values = pd.Series([1.0, 2.0, 2.0, 2.0, 3.0], index=pd.date_range("2024-01-01", periods=5, freq="10min"))
    assert _untrusted_runs(values, {"pak_frozen_readings": 3}).tolist() == [False, True, True, True, False]
    assert not _untrusted_runs(values, {"pak_frozen_readings": 4}).any()
    assert frozen_rule({}) == (6, 10.0)
    with pytest.raises(ValueError):
        frozen_rule({"pak_frozen_readings": 1})
    assert conflict_mask([10.0], [5.0], {"pak_conflict_mgkg": 4.0}).tolist() == [True]
    assert conflict_mask([10.0], [5.0], {}).tolist() == [True]            # legacy max(3, 0.5·LIMS)
    assert conflict_mask([7.0], [5.0], {}).tolist() == [False]


def test_trust_uses_the_derived_telemetry_limit():
    state = {"lab_value": 5.0, "lab_age_hours": 1.0, "lab_usable": True, "pak_value": 5.0,
             "pak_age_minutes": 0.0, "pak_usable": True, "telemetry_missing_fraction": 0.08}
    assert DataTrustAgent({}).assess(state).usable
    refused = DataTrustAgent({"telemetry_max_missing_fraction": 0.05}).assess(state)
    assert not refused.usable and "5.0%" in " ".join(refused.reasons)


def test_dead_columns_are_chosen_on_the_training_period_only():
    times = pd.date_range("2024-01-01", periods=10, freq="h")
    frame = pd.DataFrame({"later_dead": [1.0] * 5 + [STUB_VALUE] * 5,
                          "early_dead": [STUB_VALUE] * 5 + [1.0] * 5}, index=times)
    _, dead_all = mask_stubs(frame)
    _, dead_train = mask_stubs(frame, until=times[5])
    assert dead_all == []
    assert dead_train == ["early_dead"]   # later stubs do not decide which columns exist
    with pytest.raises(ValueError):
        mask_stubs(frame, until=times[0])
