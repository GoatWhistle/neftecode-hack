"""The operator screen: values come from the calculation, and every state is a real state."""
import json
import re
from pathlib import Path

import pytest

from neftecode.application.services.explain import explain
from neftecode.domain.production.inventory import initial_state
from neftecode.application.use_cases.make_decision import MakeDecision
from neftecode.robustness import RobustnessCheck
from neftecode.infrastructure.config.scenario import load_scenario
from neftecode.presentation.web.ui import STATES, Screen, UiError, error_payload, render, write_screen

SCENARIOS = Path("config/scenarios")
BUDGET = 300


def built(name="sour_crude"):
    path = SCENARIOS / f"{name}.json"
    scenario = load_scenario(path)
    raw = json.loads(path.read_text())
    decision = MakeDecision(scenario, robustness_evaluator=RobustnessCheck(scenario, raw)).decide(
        budget=BUDGET, raw_scenario=raw)
    screen = Screen(decision, explain(decision, scenario),
                    inventories={k: v.inventory_t for k, v in initial_state(scenario).items()})
    return scenario, decision, screen.payload()


def embedded(page: str) -> dict:
    match = re.search(r'<script id="payload" type="application/json">(.*?)</script>', page, re.S)
    assert match, "страница не содержит встроенных данных"
    return json.loads(match.group(1))


# --- Values come from the calculation, not from the markup ---

def test_the_page_carries_the_decision_itself():
    _, decision, payload = built()
    data = embedded(render(payload))
    assert data["decision"]["decision_id"] == decision["decision_id"]
    assert data["decision"]["production_t"] == decision["production_t"]


def test_no_computed_number_is_written_into_the_markup():
    """Only the embedded JSON holds values; the template is pure structure."""
    from neftecode.presentation.web.ui import TEMPLATE
    _, decision, _ = built()
    assert str(round(decision["production_t"], 1)) not in TEMPLATE
    assert decision["decision_id"] not in TEMPLATE


def test_changing_the_decision_changes_the_page():
    _, _, hard = built("sour_crude")
    _, _, normal = built("baseline")
    assert render(hard) != render(normal)


def test_the_page_is_self_contained():
    page = render(built()[2])
    assert "http://" not in page and "https://" not in page, "страница не должна тянуть внешние ресурсы"
    assert "<script src=" not in page


# --- Every state is a real state ---

def test_the_four_states_are_declared():
    assert set(STATES) == {"loading", "error", "decision", "refusal"}


def test_the_loading_state_is_present_in_the_page():
    page = render(built()[2])
    assert 'id="loading"' in page
    assert "Загрузка решения" in page


def test_a_recommendation_renders_as_a_decision():
    assert built("sour_crude")[2]["state"] == "decision"


def test_a_hold_renders_as_a_decision_with_its_own_label():
    payload = built("baseline")[2]
    assert payload["state"] == "decision"
    assert payload["status_label"] == "Сохранить режим"


def test_a_refusal_is_a_first_class_screen_with_next_steps():
    _, decision, payload = built("no_feasible")
    assert payload["state"] == "refusal"
    assert payload["status_label"] == "Надёжной рекомендации нет"
    assert payload["explanation"]["next_steps"], "отказ без следующих шагов бесполезен"


def test_the_error_state_carries_its_message():
    payload = error_payload("сценарий не загрузился")
    assert payload["state"] == "error"
    assert "не загрузился" in render(payload)


def test_an_unknown_state_is_refused():
    with pytest.raises(UiError, match="Неизвестное состояние"):
        render({"state": "что-то"})


def test_an_unknown_decision_status_is_refused():
    with pytest.raises(UiError, match="Неизвестный статус"):
        Screen({"status": "всё хорошо"}, {}).payload()


# --- The meaning is readable without the log ---

def test_the_main_blocks_are_present_without_opening_details():
    page = render(built()[2])
    for title in ("ЧТО ДЕЛАТЬ", "ОЖИДАЕМЫЙ ЭФФЕКТ", "КАЧЕСТВО И ЗАПАС ДО ПРЕДЕЛА",
                  "ЗАПАС КОМПОНЕНТОВ", "ДОВЕРИЕ К ДАННЫМ"):
        assert title in page.upper()


def test_the_log_is_available_but_collapsed():
    page = render(built()[2])
    assert "<details>" in page
    assert "Журнал агентов" in page
    assert "Все проверки ограничений" in page


def test_the_fragility_warning_reaches_the_screen():
    _, decision, payload = built("sour_crude")
    assert decision["robustness"]["fragile"] is True
    assert "надёжным не считается" in payload["decision"]["reason"]


def test_the_scope_note_is_carried_to_the_screen():
    payload = built()[2]
    assert "не разрешает выпуск товарного топлива" in payload["decision"]["note"]


def test_inventories_reach_the_screen():
    scenario, _, payload = built()
    assert payload["inventories"]["reserve"] == scenario.tank("reserve").inventory.value


def test_a_missing_value_is_shown_as_unknown_not_as_zero():
    page = render(built()[2])
    assert "неизвестно" in page
    assert 'class="unknown"' in page


# --- A stored decision can be reviewed ---

def test_a_saved_decision_renders_without_recomputation(tmp_path):
    scenario, decision, _ = built()
    saved = tmp_path / "decision.json"
    saved.write_text(json.dumps(decision, ensure_ascii=False, default=str))
    restored = json.loads(saved.read_text())
    payload = Screen(restored, explain(restored, scenario)).payload()
    assert payload["decision"]["decision_id"] == decision["decision_id"]


def test_the_page_is_written_to_disk(tmp_path):
    target = write_screen(tmp_path / "screen.html", built()[2])
    assert target.exists()
    assert target.read_text(encoding="utf-8").startswith("<!doctype html>")


def test_rendering_is_reproducible():
    payload = built()[2]
    assert render(payload) == render(payload)


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
    assert explain({"status": "hold", "current_operation": current}, scenario)["current_operation"] == current
