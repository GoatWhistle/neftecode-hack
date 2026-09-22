
import json
from pathlib import Path

import pytest

from neftecode.bootstrap import make_demo, risk_alarm, run_demo_decision
from neftecode.infrastructure.config.trust_rules import load_trust_rules
from neftecode.infrastructure.live.advisor import LiveError, bind_forecast


BASELINE = Path("config/scenarios/baseline.json")
TRUST_CFG, _ = load_trust_rules(Path("."), Path("artifacts"))


@pytest.fixture
def raw():
    return json.loads(BASELINE.read_text(encoding="utf-8"))


@pytest.fixture
def state():
    return {"decision_time": "2026-01-05T08:00:00",
            "lab_value": 8.0, "lab_age_hours": 5.0, "lab_usable": True,
            "pak_value": 8.4, "pak_age_minutes": 10.0, "pak_usable": True,
            "pak_frozen": False, "pak_conflict": False,
            "telemetry_missing_fraction": 0.0}


def decide(raw, state, value, lower, upper, stored=None):
    forecast = {"model": "test", "value": value, "lower": lower, "upper": upper,
                "available": True, "reason": "test"}
    if stored is not None:
        for tank in raw["tanks"]:
            if tank["tank_id"] == "main":
                tank["sulfur_from_chain"] = False
                tank["properties"]["sulfur_mgkg"] = {"value": stored, "unit": "мг/кг", "source": "scenario"}
    bound = bind_forecast(raw, forecast)
    return run_demo_decision(bound, state, 400, TRUST_CFG)["decision"]


def test_normal_state_does_not_produce_unnecessary_actions(raw, state):
    decision = decide(raw, state, 6.0, 4.0, 8.0)
    assert decision["status"] == "hold"
    assert decision["selected_plan"]["changes"] == 0
    assert decision["commercial_release_allowed"] is False


def test_point_forecast_below_limit_is_not_sufficient(raw, state):
    judged_by_point = decide(json.loads(json.dumps(raw)), state, 9.0, 7.0, 9.0, stored=10.7)
    assert judged_by_point["status"] == "hold"
    decision = decide(raw, state, 9.0, 7.0, 25.0, stored=10.7)
    assert decision["status"] != "hold"
    assert decision["selected_plan"] is None or decision["selected_plan"]["changes"] > 0


@pytest.mark.parametrize(
    "forecast",
    [
        {"model": "test", "value": None, "lower": None, "upper": None, "available": True},
        {"model": "test", "value": float("nan"), "lower": 1.0, "upper": 10.0, "available": True},
        {"model": "test", "value": 10.0, "lower": 12.0, "upper": 8.0, "available": True},
        {"model": "test", "value": 10.0, "lower": 5.0, "upper": float("inf"), "available": True},
    ],
)
def test_invalid_forecast_cannot_reach_the_decision(raw, forecast):
    with pytest.raises(LiveError, match="некоррект"):
        bind_forecast(raw, forecast)


def test_no_data_refuses_before_the_optimizer(raw, state):
    broken = dict(state, lab_value=None, lab_usable=False, pak_value=None,
                  pak_usable=False, telemetry_missing_fraction=1.0)
    decision = run_demo_decision(raw, broken, 400, TRUST_CFG)["decision"]
    assert decision["status"] == "refuse"
    assert not any(item.get("agent") == "optimizer" for item in decision["trace"])


def test_released_plan_is_feasible_and_deterministic(raw, state):
    first = decide(raw, state, 12.0, 10.0, 14.0)
    second = decide(raw, state, 12.0, 10.0, 14.0)
    assert first == second
    assert first["status"] in ("hold", "recommend_scenario")
    assert first["gate"]["feasible"] is True


def test_demo_artifacts_are_built_by_the_main_decision_flow(tmp_path):
    make_demo(Path("."), tmp_path)
    demos = json.loads((tmp_path / "demo.json").read_text(encoding="utf-8"))
    assert (tmp_path / "report.md").is_file()
    assert (tmp_path / "audit.jsonl").is_file()
    assert demos["normal_synthetic"]["status"] == "hold"
    assert demos["conflict_synthetic"]["status"] == "hold"
    assert demos["conflict_synthetic"]["decision_id"] != demos["normal_synthetic"]["decision_id"], \
        "ухудшение должно дойти до прогноза наливаемой партии, даже если текущий паспорт позволяет hold"
    assert any(item.get("agent") == "optimizer"
               for item in demos["normal_synthetic"]["trace"])


def test_replay_risk_alarm_is_a_separate_observation():
    assert risk_alarm({"score": 0.8, "threshold": 0.5}) is True
    assert risk_alarm({"score": 0.2, "threshold": 0.5}) is False
    assert risk_alarm({"score": None, "threshold": 0.5}) is None
