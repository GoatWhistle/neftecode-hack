import numpy as np
import pandas as pd

from neftecode.infrastructure.live.tank_check import tank_level_check
from neftecode.infrastructure.data.data import series_frame


def frames():
    times = pd.date_range("2026-01-01", periods=24 * 6 * 10, freq="10min")
    online = pd.DataFrame({"time": times, "value": 6.0 + 0.5 * np.sin(np.arange(len(times)) / 50)})
    lab_times = times[::144][1:]
    lab = series_frame([(t.isoformat(), 6.0 + 0.5 * np.sin(i * 144 / 50) + 0.2) for i, t in enumerate(lab_times, start=1)], "т")
    cfg = {"horizon_hours": 2, "lab_delay_hours": 4, "history_window_hours": 6,
           "lab_max_age_hours": 48, "pak_max_age_minutes": 30, "pak_frozen_readings": 4, "pak_period_minutes": 10}
    return lab, online, cfg


def test_the_check_reports_error_bias_and_correlation_per_window():
    lab, online, cfg = frames()
    report = tank_level_check(lab, online, cfg, windows_hours=(6.0, 24.0), start="2026-01-02")
    assert report["samples"] == len(lab[lab.time >= "2026-01-02"])
    for name in ("last_pak", "w6", "w24"):
        row = report["summary"][name]
        assert row["n"] > 0 and row["mae"] is not None and row["bias"] is not None
    assert "Не проверка смешения" in report["scope"]
    assert report["summary"]["last_pak"]["bias"] < 0
