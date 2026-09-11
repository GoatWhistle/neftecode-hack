import pytest

from neftecode.agents import DataAgent
from neftecode.data import series_frame


def test_series_frame_refuses_non_numeric_measurements_instead_of_dropping_them():
    with pytest.raises(ValueError, match="некоррект"):
        series_frame([("2026-01-01 00:00", 5), ("2026-01-01 01:00", "offline")], "ПАК")


def test_data_agent_refuses_impossible_negative_missing_fraction():
    decision = DataAgent().assess({
        "lab_usable": True,
        "pak_usable": True,
        "pak_frozen": False,
        "pak_conflict": False,
        "telemetry_missing_fraction": -0.01,
    })
    assert decision["usable"] is False
    assert "Недостаточно свежей телеметрии" in decision["reasons"]
