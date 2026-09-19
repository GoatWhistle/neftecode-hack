import json
from pathlib import Path

import pytest

from neftecode.application.services.explain import explain
from neftecode.application.use_cases.make_decision import MakeDecision
from neftecode.domain.production.inventory import initial_state
from neftecode.evaluation.robustness import RobustnessCheck
from neftecode.infrastructure.artifacts import write_json
from neftecode.infrastructure.config.scenario import load_scenario, parse_scenario
from neftecode.presentation.web.ui import STATES, Screen, UiError, error_payload

SCENARIOS = Path("config/scenarios")
BUDGET = 300


def built(name: str = "sour_crude") -> tuple:
    path = SCENARIOS / f"{name}.json"
    scenario = load_scenario(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    decision = MakeDecision(scenario, robustness_evaluator=RobustnessCheck(
        scenario, raw, scenario_parser=parse_scenario
    )).decide(budget=BUDGET, raw_scenario=raw)
    screen = Screen(decision, explain(decision, scenario),
                    inventories={k: v.inventory_t for k, v in initial_state(scenario).items()})
    return scenario, decision, screen.payload()


def test_the_payload_carries_the_decision_itself():
    _, decision, payload = built()
    assert payload["decision"]["decision_id"] == decision["decision_id"]
    assert payload["decision"]["production_t"] == decision["production_t"]


def test_the_payload_is_pure_json():
    payload = built()[2]
    assert json.loads(json.dumps(payload, ensure_ascii=False, default=str)) is not None


def test_changing_the_decision_changes_the_payload():
    _, _, hard = built("sour_crude")
    _, _, normal = built("baseline")
    assert hard["decision"]["decision_id"] != normal["decision"]["decision_id"]


def test_the_payload_carries_no_markup():
    text = json.dumps(built()[2], ensure_ascii=False, default=str)
    for token in ("<div", "<span", "<script", "<style", "innerHTML"):
        assert token not in text


def test_the_four_states_are_declared():
    assert set(STATES) == {"loading", "error", "decision", "refusal"}


def test_a_recommendation_renders_as_a_decision():
    assert built("sour_crude")[2]["state"] == "decision"


def test_a_hold_renders_as_a_decision_with_its_own_label():
    payload = built("baseline")[2]
    assert payload["state"] == "decision"
    assert payload["status_label"] == "Сохранить режим"


def test_a_refusal_is_a_first_class_payload_with_next_steps():
    _, _, payload = built("no_feasible")
    assert payload["state"] == "refusal"
    assert payload["status_label"] == "Надёжной рекомендации нет"
    assert payload["explanation"]["next_steps"]


def test_the_error_state_carries_its_message():
    payload = error_payload("сценарий не загрузился")
    assert payload["state"] == "error"
    assert "не загрузился" in payload["message"]


def test_an_unknown_decision_status_is_refused():
    with pytest.raises(UiError, match="Неизвестный статус"):
        Screen({"status": "всё хорошо"}, {}).payload()


def test_the_main_blocks_are_present_in_the_payload():
    payload = built()[2]
    for key in ("decision", "explanation", "inventories", "sources", "title", "status_label"):
        assert key in payload


def test_the_log_and_the_gate_reach_the_payload():
    payload = built()[2]
    assert "trace" in payload["decision"]
    assert "gate" in payload["decision"]


def test_the_fragility_warning_reaches_the_payload():
    _, decision, payload = built("sour_crude")
    assert decision["robustness"]["fragile"] is True
    assert "надёжным не считается" in payload["decision"]["reason"]


def test_the_scope_note_is_carried_to_the_payload():
    assert "не разрешает выпуск товарного топлива" in built()[2]["decision"]["note"]


def test_inventories_reach_the_payload():
    scenario, _, payload = built()
    assert payload["inventories"]["reserve"] == scenario.tank("reserve").inventory.value


def test_a_missing_value_stays_none_and_is_not_replaced_by_zero():
    scenario = load_scenario(SCENARIOS / "baseline.json")
    decision = {"status": "hold", "scenario_id": "baseline", "decision_id": "d",
                "reason": "r", "production_t": None}
    payload = Screen(decision, explain(decision, scenario)).payload()
    assert payload["decision"]["production_t"] is None


def test_a_saved_decision_is_reviewed_without_recomputation(tmp_path):
    scenario, decision, _ = built()
    saved = tmp_path / "decision.json"
    saved.write_text(json.dumps(decision, ensure_ascii=False, default=str), encoding="utf-8")
    restored = json.loads(saved.read_text(encoding="utf-8"))
    payload = Screen(restored, explain(restored, scenario)).payload()
    assert payload["decision"]["decision_id"] == decision["decision_id"]


def test_the_payload_is_written_to_disk_as_json(tmp_path):
    target = tmp_path / "screen.json"
    write_json(target, built()[2])
    assert target.exists()
    assert json.loads(target.read_text(encoding="utf-8"))["state"] == "decision"


def test_building_the_payload_is_reproducible():
    scenario, decision, payload = built()
    again = Screen(decision, explain(decision, scenario),
                   inventories=payload["inventories"]).payload()
    assert again["decision"] == payload["decision"]


def test_one_step_recipe_carries_current_and_proposed_composition():
    scenario = load_scenario(SCENARIOS / "baseline.json")
    decision = {"status": "recommend_scenario", "scenario_id": "baseline",
                "decision_id": "recipe-change", "reason": "Резерв недоступен",
                "immediate_action": {"controls": {}, "recipe": {"main": 1.0},
                                     "throughput_tph": 100, "additive_dose": 0},
                "selected_plan": {"steps": [{"time_hours": 0, "controls": {},
                                             "recipe": {"main": 1.0}, "throughput_tph": 100,
                                             "additive_dose": 0}]}}
    payload = Screen(decision, explain(decision, scenario)).payload()
    assert payload["explanation"]["current_operation"]["recipe"]["reserve"] == .1
    assert payload["decision"]["immediate_action"]["recipe"] == {"main": 1.0}
    assert payload["explanation"]["component_names"]["main"] == scenario.tank("main").name


def test_explanation_prefers_the_confirmed_current_operation_from_decision():
    scenario = load_scenario(SCENARIOS / "baseline.json")
    current = {"controls": {}, "recipe": {"main": .7, "reserve": .3},
               "throughput_tph": 80, "additive_dose": .01}
    view = explain({"status": "hold", "current_operation": current}, scenario)["current_operation"]
    assert {k: view[k] for k in current} == current
    assert view["origin"]["recipe"] == "decision"
