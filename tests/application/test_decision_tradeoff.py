import json
from pathlib import Path

from neftecode.application.use_cases.make_decision import MakeDecision
from neftecode.application.services.robustness import RobustnessCheck
from neftecode.application.services.tank_estimate import default_tank_estimate_factory
from neftecode.domain.advisory.optimizer import DEFAULT_BUDGET
from neftecode.infrastructure.config.scenario import load_scenario, parse_scenario


def run(name="baseline"):
    path = Path("config/scenarios") / f"{name}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    scenario = load_scenario(path)
    maker = MakeDecision(scenario, robustness_evaluator=RobustnessCheck(scenario, raw, scenario_parser=parse_scenario),
                         scenario_parser=parse_scenario, tank_estimate_factory=default_tank_estimate_factory)
    return maker, maker.decide(budget=DEFAULT_BUDGET, raw_scenario=raw), raw


def test_tradeoff_block_describes_the_explored_pool_and_does_not_change_the_choice():
    _, decision, _ = run("sour_crude")
    tradeoff = decision["tradeoff"]
    assert tradeoff["selected_id"] == decision["selected_plan"]["plan_id"]
    assert tradeoff["pool"]["evaluated"] and tradeoff["pool"]["search_budget"] == DEFAULT_BUDGET
    assert tradeoff["horizon_hours"] > 0
    assert tradeoff["severity_profile"].startswith("severity-profile/1")
    assert "исследованному" in tradeoff["scope"]
    assert all(p["gate_passed"] for p in tradeoff["points"])
    assert sum(1 for p in tradeoff["points"] if p["stress_checked"]) == 1
    assert decision["severity"]["comparable"] is True


def test_refusal_has_no_tradeoff_and_the_hold_choice_is_not_recoloured():
    _, decision, _ = run("no_feasible")
    assert decision["status"] == "refuse" and decision["tradeoff"] is None
    _, baseline, _ = run("baseline")
    hold = next(p for p in baseline["tradeoff"]["points"] if p["is_hold"])
    assert baseline["status"] == "hold" and hold["selected"] and hold["on_front"] is False
    assert baseline["tradeoff"]["selected_on_front"] is False and baseline["tradeoff"]["selection_note"]


def test_a_plan_removed_by_a_constraint_or_veto_never_reaches_the_front():
    maker, decision, raw = run("baseline")
    outcome = maker._search(DEFAULT_BUDGET)
    front_id = next(p["candidate_id"] for p in decision["tradeoff"]["points"] if p["on_front"])
    pool = [e for e in outcome.feasible if e.candidate.candidate_id != front_id
            and e.candidate.candidate_id not in decision["tradeoff"]["points"][0].get("equivalent_ids", ())]
    assert any(e.candidate.candidate_id == front_id for e in outcome.feasible)
    from neftecode.domain.advisory.tradeoff import tradeoff_map
    shown = {p["candidate_id"] for p in tradeoff_map(pool, "hold")["points"]}
    assert front_id not in shown
