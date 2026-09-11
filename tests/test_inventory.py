"""Inventories across the plan: mass conserved, no second spending, no draining to the last point."""
import json
from pathlib import Path

import pytest

from neftecode.contracts import ContractError, TankState
from neftecode.inventory import (MIN_HOURS_OF_SUPPLY, NO_TERMINAL_RULE, InventoryError,
                                 InventoryLedger, draw_step, initial_state)
from neftecode.scenario import load_scenario, parse_scenario

BASELINE = Path("config/scenarios/baseline.json")
SOUR = Path("config/scenarios/sour_crude.json")


def ledger(path=BASELINE, **policy):
    raw = json.loads(Path(path).read_text())
    raw["policy"].update(policy)
    return InventoryLedger(parse_scenario(raw))


def tanks(path=BASELINE):
    return initial_state(load_scenario(path))


# --- Mass is conserved and never spent twice ---

def test_drawing_reduces_the_stock_by_exactly_what_was_taken():
    before = tanks()
    result = draw_step(before, {"reserve": 1.0}, throughput_tph=20.0, hours=2.0)
    assert result.drawn_t["reserve"] == pytest.approx(40.0)
    assert result.tanks["reserve"].inventory_t == pytest.approx(600.0 - 40.0)


def test_the_input_state_is_not_mutated():
    before = tanks()
    draw_step(before, {"reserve": 1.0}, 20.0, 2.0)
    assert before["reserve"].inventory_t == pytest.approx(600.0), "исходное состояние изменено на месте"


def test_replaying_the_same_step_does_not_spend_the_stock_twice():
    before = tanks()
    once = draw_step(before, {"reserve": 1.0}, 20.0, 1.0)
    again = draw_step(before, {"reserve": 1.0}, 20.0, 1.0)
    assert once.tanks["reserve"].inventory_t == pytest.approx(again.tanks["reserve"].inventory_t)


def test_sequential_steps_accumulate_the_draw():
    state = tanks()
    for _ in range(3):
        state = draw_step(state, {"reserve": 1.0}, 20.0, 1.0).tanks
    assert state["reserve"].inventory_t == pytest.approx(600.0 - 60.0)


def test_inflow_is_added_during_the_step():
    result = draw_step(tanks(), {"reserve": 1.0}, 20.0, 2.0)
    assert result.tanks["main"].inventory_t == pytest.approx(4000.0 + 95.0 * 2.0)


def test_inventory_never_goes_negative():
    state = {"r": TankState("r", True, 10.0, {"sulfur_mgkg": 2.0}, 0.0, 100.0)}
    result = draw_step(state, {"r": 1.0}, 50.0, 1.0)
    assert result.feasible is False
    assert result.tanks["r"].inventory_t == pytest.approx(10.0), "неудавшийся отбор не трогает остаток"


def test_contract_refuses_a_withdrawal_beyond_the_stock():
    with pytest.raises(ContractError, match="превышает остаток"):
        TankState("r", True, 10.0, {"sulfur_mgkg": 2.0}).draw(11.0)


# --- Availability and outflow limits ---

def test_an_unavailable_tank_cannot_be_used():
    state = tanks(Path("config/scenarios/no_feasible.json"))
    result = draw_step(state, {"reserve": 1.0}, 10.0, 1.0)
    assert result.feasible is False
    assert any("недоступен" in reason for reason in result.reasons)


def test_exceeding_the_outflow_limit_is_reported_with_both_numbers():
    result = draw_step(tanks(), {"reserve": 1.0}, 50.0, 1.0)
    assert result.feasible is False
    assert any("при пределе отбора" in reason for reason in result.reasons)


def test_drawing_at_exactly_the_outflow_limit_is_allowed():
    assert draw_step(tanks(), {"reserve": 1.0}, 30.0, 1.0).feasible is True


def test_a_component_with_zero_share_is_not_drawn_at_all():
    result = draw_step(tanks(), {"main": 1.0, "reserve": 0.0}, 100.0, 1.0)
    assert "reserve" not in result.drawn_t
    assert result.feasible is True


def test_an_unknown_tank_in_the_recipe_is_reported():
    result = draw_step(tanks(), {"ghost": 1.0}, 10.0, 1.0)
    assert result.feasible is False
    assert any("отсутствует" in reason for reason in result.reasons)


@pytest.mark.parametrize("value", [-1.0, float("nan")])
def test_impossible_throughput_or_duration_is_refused(value):
    with pytest.raises(InventoryError):
        draw_step(tanks(), {"main": 1.0}, value, 1.0)
    with pytest.raises(InventoryError):
        draw_step(tanks(), {"main": 1.0}, 100.0, value)


# --- Running a whole plan ---

def test_a_sustainable_plan_is_feasible_and_leaves_stock():
    result = ledger().run_plan([(0.0, {"main": 0.7, "reserve": 0.3}, 100.0)])
    assert result["feasible"] is True
    assert result["final_inventories"]["reserve"] > 0
    assert result["first_failure"] is None


def test_a_blend_feasible_now_but_not_for_the_whole_plan_is_rejected():
    """The reserve in the sour-crude scenario lasts exactly to the horizon and no further."""
    result = ledger(SOUR).run_plan([(0.0, {"main": 0.7, "reserve": 0.3}, 100.0)])
    assert result["feasible"] is False
    assert result["final_inventories"]["reserve"] == pytest.approx(0.0)


def test_the_step_where_the_plan_fails_is_identified():
    result = ledger(SOUR).run_plan([(0.0, {"main": 0.5, "reserve": 0.5}, 100.0)])
    assert result["first_failure"] is not None
    assert result["first_failure"]["time_hours"] == 0.0


def test_each_step_is_held_until_the_next_one():
    result = ledger().run_plan([(0.0, {"reserve": 1.0}, 20.0), (1.0, {"main": 1.0}, 20.0)])
    assert result["timeline"][0]["duration_hours"] == pytest.approx(1.0)
    assert result["timeline"][1]["duration_hours"] == pytest.approx(2.0), "последний шаг держится до горизонта"


def test_steps_out_of_order_are_refused():
    with pytest.raises(InventoryError, match="по возрастанию"):
        ledger().run_plan([(2.0, {"main": 1.0}, 100.0), (1.0, {"main": 1.0}, 100.0)])


def test_the_timeline_records_inventories_at_every_step():
    result = ledger().run_plan([(0.0, {"reserve": 1.0}, 20.0), (1.5, {"reserve": 1.0}, 20.0)])
    assert len(result["timeline"]) == 2
    assert result["timeline"][0]["inventories"]["reserve"] > result["timeline"][1]["inventories"]["reserve"]


# --- The end of the horizon is not the end of the plant ---

def test_a_plan_that_drains_the_reserve_to_the_last_point_fails_the_terminal_rule():
    result = ledger(SOUR).run_plan([(0.0, {"main": 0.7, "reserve": 0.3}, 100.0)])
    assert result["terminal"]["satisfied"] is False
    assert "после горизонта" in result["terminal"]["reason"]


def test_a_plan_leaving_enough_supply_passes_the_terminal_rule():
    result = ledger().run_plan([(0.0, {"main": 0.9, "reserve": 0.1}, 100.0)])
    assert result["terminal"]["satisfied"] is True
    assert result["terminal"]["rule"] == MIN_HOURS_OF_SUPPLY


def test_without_a_terminal_rule_nothing_is_demanded_at_the_end():
    result = ledger(SOUR, terminal_inventory_rule=NO_TERMINAL_RULE).run_plan(
        [(0.0, {"main": 0.7, "reserve": 0.3}, 100.0)])
    assert result["terminal"]["satisfied"] is True
    assert "не задано" in result["terminal"]["reason"]


def test_a_longer_required_supply_rejects_a_plan_a_shorter_one_accepts():
    plan = [(0.0, {"main": 0.9, "reserve": 0.1}, 100.0)]
    assert ledger(terminal_min_hours=1.0).run_plan(plan)["terminal"]["satisfied"] is True
    assert ledger(terminal_min_hours=100.0).run_plan(plan)["terminal"]["satisfied"] is False


def test_an_unknown_terminal_rule_is_refused_rather_than_ignored():
    with pytest.raises(InventoryError, match="неизвестное правило"):
        ledger(terminal_inventory_rule="как-нибудь").run_plan([(0.0, {"main": 1.0}, 100.0)])


def test_the_reported_rule_explains_why_the_terminal_check_exists():
    result = ledger().run_plan([(0.0, {"main": 1.0}, 100.0)])
    assert "опустошения резерва к последней точке" in result["rule"]


# --- Initial state comes from the scenario ---

def test_initial_state_matches_the_scenario():
    state = tanks()
    assert state["main"].inventory_t == 4000.0
    assert state["reserve"].max_outflow_tph == 30.0
    assert state["light"].properties["cetane_number"] is None
    assert state["main"].provenance == "scenario"
