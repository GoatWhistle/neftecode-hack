from pathlib import Path

from neftecode.application.contracts import DecisionCommand
from neftecode.application.use_cases.make_decision import MakeDecision
from neftecode.domain.shared.primitives import PRODUCT_LIMITS
from neftecode.infrastructure.config.scenario import load_scenario

BASELINE = Path("config/scenarios/baseline.json")
SOUR = Path("config/scenarios/sour_crude.json")
NO_FEASIBLE = Path("config/scenarios/no_feasible.json")


def decide(path: Path, budget: int = 60) -> dict:
    return MakeDecision(load_scenario(str(path))).execute(DecisionCommand(budget=budget))


def test_hold_decision_carries_selected_and_hold_points_from_same_gate():
    decision = decide(BASELINE)
    assert decision["status"] == "hold"
    consequences = decision["consequences"]
    assert consequences["selected_id"] == "hold" == decision["gate"]["plan_id"]
    assert consequences["hold"]["source"] == "selected_is_hold"
    assert consequences["horizon_hours"] == decision["gate"]["checks"][-1]["time_hours"] \
        or consequences["horizon_hours"] > 0
    assert len(consequences["series"]) == len(PRODUCT_LIMITS)
    for series in consequences["series"]:
        selected_points = series["candidates"]["selected"]["points"]
        hold_points = series["candidates"]["hold"]["points"]
        assert selected_points == hold_points  # hold is the selected plan here
        gate_points = [{"t": c["time_hours"], "value": c["observed"], "status": c["status"]}
                       for c in decision["gate"]["checks"]
                       if c["constraint_id"] == f"quality.{series['limit_id']}"]
        assert selected_points == gate_points


def test_recommend_scenario_reports_hold_from_the_same_pool_or_explicit_unavailability():
    decision = decide(SOUR)
    assert decision["status"] == "recommend_scenario"
    consequences = decision["consequences"]
    assert consequences["selected_id"] != "hold"
    assert consequences["hold"]["source"] in ("search_pool", None)
    if consequences["hold"]["available"]:
        for series in consequences["series"]:
            assert "hold" in series["candidates"]
    else:
        assert consequences["hold"]["reason"]
        for series in consequences["series"]:
            assert "hold" not in series["candidates"]
    for series in consequences["series"]:
        assert series["candidates"]["selected"]["candidate_id"] == consequences["selected_id"]


def test_consequences_do_not_add_extra_evaluator_calls():
    """_consequences не заводит второй evaluator: последний вызов planner.evaluate в decide()
    остаётся финальной перепроверкой выбранного плана, а не пересчётом hold после неё —
    от этого зависит поведение других проверок decide() (например, отказ при провале
    именно финальной перепроверки)."""
    scenario = load_scenario(str(SOUR))
    maker = MakeDecision(scenario)
    calls: list[str] = []
    original = maker.planner.evaluate

    def counting(plan, *args, **kwargs):
        calls.append(plan.plan_id)
        return original(plan, *args, **kwargs)

    maker.planner.evaluate = counting
    decision = maker.decide(budget=60)
    assert decision["consequences"] is not None
    assert calls[-1] == decision["gate"]["plan_id"]


def test_refusal_carries_no_consequences_block():
    decision = decide(NO_FEASIBLE, budget=10)
    assert decision["status"] == "refuse"
    assert decision.get("consequences") is None


def test_applicability_and_limit_source_are_reported():
    decision = decide(BASELINE)
    consequences = decision["consequences"]
    assert consequences["applicability"]["selected"][0]["t"] == 0.0
    for series in consequences["series"]:
        assert series["unit"]
        assert series["limit"]["source"] in ("given", "derived", "measured", None)
