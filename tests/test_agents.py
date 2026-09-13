import json
from pathlib import Path

import pytest

from neftecode.infrastructure.ml.agents import Coordinator, Forecast


@pytest.fixture
def config():
    return json.loads((Path(__file__).resolve().parents[1] / "config/blending-demo.json").read_text())


@pytest.fixture
def state():
    return {"lab_value": 8.0, "lab_age_hours": 5.0, "lab_usable": True,
            "pak_value": 8.4, "pak_age_minutes": 10.0, "pak_usable": True,
            "pak_frozen": False, "pak_conflict": False, "telemetry_missing_fraction": 0}


def test_normal_state_does_not_produce_unnecessary_actions(config, state):
    d = Coordinator(config).run(state, Forecast(6, 4, 8, "test"))
    assert d["status"] == "hold"
    assert d["chosen"]["reserve_fraction"] == config["current_reserve_fraction"]
    assert d["commercial_release_allowed"] is False


def test_equipment_veto_causes_a_real_second_search(config, state):
    d = Coordinator(config).run(state, Forecast(12, 10, 14, "test"))
    assert d["status"] == "recommend_scenario"
    assert any(t.get("vetoed_quality_feasible", 0) > 0 for t in d["trace"])
    assert any(t.get("round") == 2 and t["agent"] == "optimizer" for t in d["trace"])
    assert d["chosen"]["throughput_tph"] == 70
    assert d["chosen"]["reserve_fraction"] == .4
    assert d["chosen"]["quality"]["sulfur_upper"] == pytest.approx(9.6)


def test_point_forecast_below_limit_is_not_sufficient(config, state):
    d = Coordinator(config).run(state, Forecast(9, 7, 11, "test"))
    assert d["status"] != "hold"
    assert d["candidates"][0]["quality"]["allowed"] is False


@pytest.mark.parametrize("forecast", [Forecast(None, None, None, "test"), Forecast(float("nan"), 1, 10, "test"),
                                    Forecast(10, 12, 8, "test"), Forecast(10, 5, float("inf"), "test")])
def test_invalid_forecast_refuses_without_nan_json(config, state, forecast):
    d = Coordinator(config).run(state, forecast)
    assert d["status"] == "refuse"
    assert d["chosen"] is None
    json.dumps(d, allow_nan=False)


def test_frozen_pak_requires_separate_fallback(config, state):
    state["pak_frozen"] = True
    coordinator = Coordinator(config)
    assert coordinator.run(state, Forecast(6, 4, 8, "main"))["status"] == "refuse"
    d = coordinator.run(state, Forecast(6, 4, 8, "main"), Forecast(12, 10, 14, "fallback"))
    assert d["forecast"]["model"] == "fallback"
    assert d["status"] != "hold"


def test_no_data_and_no_feasible_actions_both_refuse(config, state):
    coordinator = Coordinator(config)
    assert coordinator.run(dict(state, lab_usable=False, pak_usable=False), Forecast(6, 4, 8, "test"))["status"] == "refuse"
    assert coordinator.run(state, Forecast(100, 80, 120, "test"))["status"] == "refuse"


def test_all_accepted_candidates_obey_hard_constraints(config, state):
    d = Coordinator(config).run(state, Forecast(12, 10, 14, "test"))
    for c in d["candidates"]:
        if c["allowed"]:
            assert c["reserve_fraction"] + c["main_fraction"] == pytest.approx(1)
            assert c["quality"]["sulfur_upper"] <= 10
            assert c["reserve_fraction"] * c["throughput_tph"] <= config["reserve_pump_limit_tph"]
            assert c["reliability"]["allowed"]


def test_replay_decision_is_deterministic(config, state):
    coordinator = Coordinator(config)
    assert coordinator.run(state, Forecast(12, 10, 14, "test")) == coordinator.run(state, Forecast(12, 10, 14, "test"))


def test_invalid_scenario_cannot_reach_optimizer(config):
    config["reserve_pump_limit_tph"] = 0
    with pytest.raises(ValueError):
        Coordinator(config)
