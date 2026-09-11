import pytest

from neftecode.agents import DataAgent
from neftecode.data import series_frame


def test_series_frame_refuses_non_numeric_measurements_instead_of_dropping_them():
    with pytest.raises(ValueError, match="некоррект"):
        series_frame([("2026-01-01 00:00", 5), ("2026-01-01 01:00", "offline")], "ПАК")


def test_data_agent_refuses_impossible_negative_missing_fraction():
    decision = DataAgent().assess({
        "lab_value": 8.0,
        "lab_usable": True,
        "pak_value": 8.4,
        "pak_age_minutes": 10.0,
        "pak_usable": True,
        "pak_frozen": False,
        "pak_conflict": False,
        "telemetry_missing_fraction": -0.01,
    })
    assert decision["usable"] is False
    assert any("доля пропусков" in reason for reason in decision["reasons"])
    assert "полная свежая телеметрия за последний срез" in decision["missing_requirements"]
