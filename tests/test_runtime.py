import json
from pathlib import Path

import pandas as pd
import pytest

from neftecode.agents import Coordinator, Forecast
from neftecode.runtime import decision_at, validate_origin


def test_query_cannot_use_a_model_before_its_calibration_is_available():
    bundle = {"config": {"calibration_end": "2026-01-01"}}
    with pytest.raises(ValueError, match="утечку"):
        validate_origin("2025-12-31 23:59", bundle)
    assert validate_origin("2026-01-01", bundle) == pd.Timestamp("2026-01-01")
    with pytest.raises(ValueError, match="без часового пояса"):
        validate_origin("2026-01-01T00:00:00Z", bundle)


def test_query_without_recent_data_refuses_before_evaluating_models():
    times = pd.date_range("2025-12-01", periods=20, freq="10min")
    signals = pd.DataFrame({"ht.P3": 1.0}, index=times)
    readings = pd.DataFrame({"time": times, "value": 7.0})
    cfg = {"calibration_end": "2026-01-01", "lab_delay_hours": 4, "history_window_hours": 6,
           "lab_max_age_hours": 48, "pak_max_age_minutes": 30, "horizon_hours": 2}
    scenario = json.loads((Path(__file__).resolve().parents[1] / "config/blending-demo.json").read_text())
    # No models supplied: stale inputs must refuse without trying to run a predictor.
    result = decision_at(signals, readings, readings, {"config": cfg}, "2026-01-01", scenario)
    assert result["status"] == "refuse"
    assert result["forecast"]["model"] == "unavailable"


def test_risk_fallback_follows_data_trust_and_cannot_relax_quality_gate():
    scenario = json.loads((Path(__file__).resolve().parents[1] / "config/blending-demo.json").read_text())
    state = {"lab_value": 8.0, "lab_age_hours": 5.0, "lab_usable": True,
             "pak_value": 8.4, "pak_age_minutes": 10.0, "pak_usable": True,
             "pak_frozen": True, "telemetry_missing_fraction": 0}
    risk = {"main": {"model": "main", "score": .9, "threshold": .5},
            "fallback": {"model": "fallback", "score": .1, "threshold": .5}}
    result = Coordinator(scenario).run(state, Forecast(5, 4, 8, "main"), Forecast(100, 80, 120, "fallback"), risk)
    assert result["risk"]["model"] == "fallback"
    assert result["risk"]["alarm"] is False
    assert result["status"] == "refuse"
