import json
import pickle

import numpy as np
import pandas as pd
import pytest

from neftecode.infrastructure.history.source import LocalHistorySource


@pytest.fixture
def history(tmp_path, monkeypatch):
    signals = pd.DataFrame({"ht.T6": 367.8, "ht.F9": 206.1, "ht.F26": 206.1},
                           index=pd.date_range("2025-12-30", "2026-01-06", freq="10min"))
    lab = pd.DataFrame({"time": pd.to_datetime(["2026-01-03T10:00", "2026-01-04T10:00", "2026-01-05T10:00"]),
                        "value": [7.0, 8.0, 999.0]})
    online = pd.DataFrame({"time": signals.index, "value": 8 + np.sin(np.arange(len(signals)) / 9) * .1})
    cfg = {"train_end": "2025-01-01", "calibration_end": "2026-01-01", "horizon_hours": 2,
           "history_window_hours": 6, "lab_delay_hours": 4, "lab_max_age_hours": 48,
           "pak_max_age_minutes": 30, "pak_conflict_mgkg": 5, "telemetry_max_missing_fraction": .1,
           "pak_frozen_readings": 4, "pak_period_minutes": 10}
    bundle = {"config": cfg, "selected": "last_lab", "fallback": "last_lab", "radii": {"last_lab": .1},
              "manifest": {"fingerprint": "test-model"}}
    out = tmp_path / "artifacts"
    out.mkdir()
    (out / "model.pkl").write_bytes(pickle.dumps(bundle))
    task = tmp_path / "task"
    (task / "data").mkdir(parents=True)
    for path in ["data/avt_tags.csv", "data/242000_tags.csv", "ЛИМС.xlsx", "Выгрузка.xlsx"]:
        (task / path).touch()
    folder = tmp_path / "research/data"
    folder.mkdir(parents=True)
    (folder / "excluded-periods.json").write_text(json.dumps({"pak_frozen_intervals": [
        {"from": "2026-01-05T00:00:00", "to": "2026-01-05T02:00:00", "reason": "Зависание ПАК"}]}))
    monkeypatch.setattr("neftecode.infrastructure.history.source.load_sources", lambda *args: (signals, lab, online))
    return LocalHistorySource(tmp_path, out), signals, lab, online, bundle
