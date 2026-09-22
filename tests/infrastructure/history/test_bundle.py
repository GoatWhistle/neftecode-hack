import hashlib
import pickle

import pytest

from neftecode.infrastructure.data.alignment import FROZEN_FORECAST_SELECTION
from neftecode.infrastructure.history.bundle import history_bundle


def config():
    return {"horizon_hours": 2, "lab_delay_hours": 4, "history_window_hours": 6,
            "forecast_selection": dict(FROZEN_FORECAST_SELECTION)}


def test_metadata_migration_requires_matching_evidence_hash(tmp_path, monkeypatch):
    path = tmp_path / "research/forecast/rolling-f4.json"
    path.parent.mkdir(parents=True)
    path.write_text("evidence")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setitem(FROZEN_FORECAST_SELECTION, "evidence_sha256", digest)
    cfg = config()
    cfg["forecast_selection"]["evidence"] = "context/forecast-research/rolling-f4.json"
    raw = pickle.dumps({"config": cfg, "numeric_parameter": 123})
    bundle, migrations = history_bundle(tmp_path, raw)
    assert bundle["numeric_parameter"] == 123
    assert bundle["config"]["forecast_selection"]["evidence"] == "research/forecast/rolling-f4.json"
    assert migrations[0]["verified_sha256"] == digest
    assert pickle.loads(raw)["config"]["forecast_selection"]["evidence"].startswith("context/")
    path.write_text("other evidence")
    with pytest.raises(ValueError, match="хешем"):
        history_bundle(tmp_path, raw)


def test_no_migration_for_current_bundle(tmp_path):
    _, migrations = history_bundle(tmp_path, pickle.dumps({"config": config()}))
    assert migrations == []


@pytest.mark.parametrize("delay", [-1, 4.1, float("nan")])
def test_bad_lims_delay_rejects_history_bundle(tmp_path, delay):
    cfg = config()
    cfg["lab_delay_hours"] = delay
    with pytest.raises(ValueError, match="lab_delay_hours"):
        history_bundle(tmp_path, pickle.dumps({"config": cfg}))
