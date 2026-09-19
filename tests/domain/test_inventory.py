from dataclasses import replace
import json
from pathlib import Path

import pytest

from neftecode.domain.shared.primitives import ContractError
from neftecode.domain.production.state import TankState
from neftecode.domain.production.inventory import (MIN_HOURS_OF_SUPPLY, NO_TERMINAL_RULE, InventoryError,
                                 InventoryLedger, draw_step, initial_state)
from neftecode.infrastructure.config.scenario import load_scenario, parse_scenario

BASELINE = Path("config/scenarios/baseline.json")
SOUR = Path("config/scenarios/sour_crude.json")


def ledger(path=BASELINE, **policy):
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    raw["policy"].update(policy)
    return InventoryLedger(parse_scenario(raw))


def tanks(path=BASELINE):
    return initial_state(load_scenario(path))


def with_light(path=BASELINE, **policy) -> dict:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    raw["policy"].update(policy)
    for tank in raw["tanks"]:
        if tank["tank_id"] == "light":
            tank["available"] = True
    return raw


def stock_tanks(path=BASELINE) -> dict[str, TankState]:
    return initial_state(parse_scenario(with_light(path)))


def stock_ledger(path=BASELINE, **policy) -> InventoryLedger:
    return InventoryLedger(parse_scenario(with_light(path, **policy)))



def test_drawing_reduces_the_stock_by_exactly_what_was_taken():
    before = stock_tanks()
    result = draw_step(before, {"light": 1.0}, throughput_tph=20.0, hours=2.0)
    assert result.drawn_t["light"] == pytest.approx(40.0)
    assert result.tanks["light"].inventory_t == pytest.approx(900.0 - 40.0)


def test_drawing_an_on_demand_component_produces_it_instead_of_depleting_a_stock():
    before = tanks()
    result = draw_step(before, {"reserve": 1.0}, throughput_tph=20.0, hours=2.0)
    assert result.drawn_t["reserve"] == pytest.approx(40.0)
    assert result.tanks["reserve"].inventory_t == pytest.approx(0.0)
    assert result.tanks["reserve"].produced_t == pytest.approx(40.0)


def test_the_input_state_is_not_mutated():
    before = stock_tanks()
    draw_step(before, {"light": 1.0}, 20.0, 2.0)
    assert before["light"].inventory_t == pytest.approx(900.0), "исходное состояние изменено на месте"


def test_replaying_the_same_step_does_not_spend_the_stock_twice():
    before = stock_tanks()
    once = draw_step(before, {"light": 1.0}, 20.0, 1.0)
    again = draw_step(before, {"light": 1.0}, 20.0, 1.0)
    assert once.tanks["light"].inventory_t == pytest.approx(again.tanks["light"].inventory_t)


def test_sequential_steps_accumulate_the_draw():
    state = stock_tanks()
    for _ in range(3):
        state = draw_step(state, {"light": 1.0}, 20.0, 1.0).tanks
    assert state["light"].inventory_t == pytest.approx(900.0 - 60.0)


def test_sequential_steps_accumulate_what_an_on_demand_component_produced():
    state = tanks()
    for _ in range(3):
        state = draw_step(state, {"reserve": 1.0}, 20.0, 1.0).tanks
    assert state["reserve"].produced_t == pytest.approx(60.0)


def test_inflow_is_added_during_the_step():
    result = draw_step(tanks(), {"reserve": 1.0}, 20.0, 2.0)
    inflow = tanks()["main"].inflow_tph
    assert result.tanks["main"].inventory_t == pytest.approx(4000.0 + inflow * 2.0)


def test_well_mixed_inflow_preserves_mass_and_updates_properties_gradually():
    before = tanks()
    result = draw_step(before, {"main": 0.0}, 0.0, 1.0,
                       {"main": {"sulfur_mgkg": 20.0, "t95_c": 380.0, "cetane_number": 50.0}})
    inflow = tanks()["main"].inflow_tph
    assert result.tanks["main"].inventory_t == pytest.approx(4000.0 + inflow)
    assert result.tanks["main"].properties["t95_c"] == pytest.approx(
        (4000.0 * 352.0 + inflow * 380.0) / (4000.0 + inflow))
    assert result.tanks["main"].properties["t95_c"] < 380.0


def test_unknown_positive_inflow_is_reported_as_unknown_critical_property():
    result = draw_step(tanks(), {"main": 0.0}, 0.0, 1.0,
                       {"main": {"sulfur_mgkg": None, "t95_c": 380.0, "cetane_number": 50.0}})
    assert result.feasible is False
    assert any("неизвестные свойства" in reason for reason in result.reasons)


def test_inventory_never_goes_negative():
    state = {"r": TankState("r", True, 10.0, {"sulfur_mgkg": 2.0}, 0.0, 100.0)}
    result = draw_step(state, {"r": 1.0}, 50.0, 1.0)
    assert result.feasible is False
    assert result.tanks["r"].inventory_t == pytest.approx(10.0), "неудавшийся отбор не трогает остаток"


def test_contract_refuses_a_withdrawal_beyond_the_stock():
    with pytest.raises(ContractError, match="превышает остаток"):
        TankState("r", True, 10.0, {"sulfur_mgkg": 2.0}).draw(11.0)



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


def test_drawing_above_max_outflow_does_not_change_stock():
    before = tanks()
    result = draw_step(before, {"reserve": 1.0}, 31.0, 1.0)
    assert result.feasible is False
    assert result.tanks["reserve"].inventory_t == pytest.approx(before["reserve"].inventory_t)


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



def test_a_sustainable_plan_is_feasible_and_leaves_stock():
    result = stock_ledger().run_plan([(0.0, {"main": 0.9, "light": 0.1}, 100.0)])
    assert result["feasible"] is True
    assert result["final_inventories"]["light"] > 0
    assert result["first_failure"] is None


def test_a_plan_within_the_production_limit_of_an_on_demand_component_is_feasible():
    result = ledger().run_plan([(0.0, {"main": 0.7, "reserve": 0.3}, 100.0)])
    assert result["feasible"] is True
    assert result["first_failure"] is None


def test_a_plan_beyond_the_production_limit_of_an_on_demand_component_is_rejected():
    result = ledger().run_plan([(0.0, {"main": 0.6, "reserve": 0.4}, 100.0)])
    assert result["feasible"] is False
    assert result["first_failure"] is not None
    assert any("при пределе отбора" in reason for reason in result["first_failure"]["reasons"])


def with_stock(mass_t: float, **policy) -> InventoryLedger:
    raw = with_light(BASELINE, **policy)
    for tank in raw["tanks"]:
        if tank["tank_id"] == "light":
            tank["inventory"]["value"] = mass_t
    return InventoryLedger(parse_scenario(raw))


def test_a_blend_feasible_now_but_not_for_the_whole_plan_is_rejected():
    plan = [(0.0, {"main": 0.9, "light": 0.1}, 100.0)]
    assert with_stock(200.0).run_plan(plan)["feasible"] is True
    scarce = with_stock(10.0).run_plan(plan)
    assert scarce["feasible"] is False
    assert scarce["first_failure"] is not None


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
    result = stock_ledger().run_plan([(0.0, {"light": 1.0}, 20.0), (1.5, {"light": 1.0}, 20.0)])
    assert len(result["timeline"]) == 2
    assert result["timeline"][0]["inventories"]["light"] > result["timeline"][1]["inventories"]["light"]
    assert result["timeline"][0]["end_inventories"]["light"] == pytest.approx(
        result["timeline"][1]["inventories"]["light"])



def test_a_plan_that_drains_the_stock_to_the_last_point_fails_the_terminal_rule():
    result = with_stock(30.0).run_plan([(0.0, {"main": 0.9, "light": 0.1}, 100.0)])
    assert result["first_failure"] is None, "сами шаги проходят"
    assert result["final_inventories"]["light"] == pytest.approx(0.0)
    assert result["terminal"]["satisfied"] is False
    assert "после горизонта" in result["terminal"]["reason"]
    assert result["feasible"] is False


def test_an_on_demand_component_is_not_asked_for_a_terminal_stock():
    result = ledger().run_plan([(0.0, {"main": 0.7, "reserve": 0.3}, 100.0)])
    assert result["final_inventories"]["reserve"] == pytest.approx(0.0)
    assert result["terminal"]["satisfied"] is True
    assert result["terminal"]["shortfalls"] == []


def test_a_plan_leaving_enough_supply_passes_the_terminal_rule():
    result = stock_ledger().run_plan([(0.0, {"main": 0.9, "light": 0.1}, 100.0)])
    assert result["terminal"]["satisfied"] is True
    assert result["terminal"]["rule"] == MIN_HOURS_OF_SUPPLY


def test_without_a_terminal_rule_nothing_is_demanded_at_the_end():
    result = ledger(SOUR, terminal_inventory_rule=NO_TERMINAL_RULE).run_plan(
        [(0.0, {"main": 0.7, "reserve": 0.3}, 100.0)])
    assert result["terminal"]["satisfied"] is True
    assert "не задано" in result["terminal"]["reason"]


def test_a_longer_required_supply_rejects_a_plan_a_shorter_one_accepts():
    plan = [(0.0, {"main": 0.9, "light": 0.1}, 100.0)]
    assert stock_ledger(terminal_min_hours=1.0).run_plan(plan)["terminal"]["satisfied"] is True
    assert stock_ledger(terminal_min_hours=100.0).run_plan(plan)["terminal"]["satisfied"] is False


def test_an_unknown_terminal_rule_is_refused_rather_than_ignored():
    with pytest.raises(InventoryError, match="неизвестное правило"):
        ledger(terminal_inventory_rule="как-нибудь").run_plan([(0.0, {"main": 1.0}, 100.0)])


def test_the_reported_rule_explains_why_the_terminal_check_exists():
    result = ledger().run_plan([(0.0, {"main": 1.0}, 100.0)])
    assert "опустошения резерва к последней точке" in result["rule"]



def test_initial_state_matches_the_scenario():
    state = tanks()
    assert state["main"].inventory_t == 4000.0
    assert state["reserve"].max_outflow_tph == 30.0
    assert state["light"].properties["cetane_number"] is None
    assert state["main"].provenance == "scenario"



def prepared(lead_hours: float = 0.0, rate_tph: float = 30.0, path=BASELINE) -> dict[str, TankState]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    for tank in raw["tanks"]:
        if tank.get("on_demand"):
            tank["production_lead_time_hours"]["value"] = lead_hours
            tank["production_rate_tph"]["value"] = rate_tph
    return initial_state(parse_scenario(raw))


def test_the_production_rate_bounds_a_draw_even_when_the_outflow_limit_allows_it():
    state = prepared(rate_tph=10.0)
    state["reserve"] = replace(state["reserve"], max_outflow_tph=100.0)
    result = draw_step(state, {"reserve": 1.0}, throughput_tph=60.0, hours=1.0)
    assert result.feasible is False
    assert "произвести можно 10.00 т" in result.reasons[0]


def test_a_draw_within_the_production_rate_is_allowed():
    result = draw_step(prepared(rate_tph=30.0), {"reserve": 1.0}, throughput_tph=30.0, hours=1.0)
    assert result.feasible is True
    assert result.tanks["reserve"].produced_t == pytest.approx(30.0)


def test_nothing_can_be_drawn_before_the_preparation_time_has_passed():
    result = draw_step(prepared(lead_hours=2.0), {"reserve": 1.0}, throughput_tph=10.0, hours=1.0)
    assert result.feasible is False
    assert "подготовка 2 ч" in result.reasons[0]


def test_the_component_becomes_available_once_preparation_is_over():
    state = prepared(lead_hours=1.0, rate_tph=30.0)
    first = draw_step(state, {"main": 1.0}, throughput_tph=100.0, hours=1.0)
    assert first.feasible is True
    second = draw_step(first.tanks, {"reserve": 1.0}, throughput_tph=30.0, hours=1.0)
    assert second.feasible is True
    assert second.tanks["reserve"].produced_t == pytest.approx(30.0)


def test_consumption_accumulated_over_steps_never_exceeds_what_was_produced_by_then():
    state = prepared(rate_tph=30.0)
    hours = 0.0
    for _ in range(4):
        result = draw_step(state, {"main": 0.0, "reserve": 1.0}, throughput_tph=30.0, hours=0.5)
        assert result.feasible is True
        state = result.tanks
        hours += 0.5
        assert state["reserve"].produced_t <= state["reserve"].makeable_by(hours) + 1e-9


def test_a_plan_that_asks_for_more_than_production_can_make_is_rejected_with_the_moment_named():
    result = draw_step(prepared(rate_tph=30.0), {"reserve": 1.0}, throughput_tph=30.0, hours=1.0)
    second = draw_step(result.tanks, {"reserve": 1.0}, throughput_tph=30.0, hours=1.0)
    assert second.feasible is True
    state = prepared(rate_tph=5.0)
    state["reserve"] = replace(state["reserve"], max_outflow_tph=100.0)
    blocked = draw_step(state, {"reserve": 1.0}, throughput_tph=30.0, hours=2.0)
    assert blocked.feasible is False
    assert "к 2 ч" in blocked.reasons[0]


def test_every_scenario_declares_how_its_on_demand_component_is_produced():
    for path in sorted(Path("config/scenarios").glob("*.json")):
        scenario = load_scenario(path)
        for tank in scenario.tanks:
            if tank.on_demand:
                assert tank.production_rate_tph > 0, path.name
                assert tank.production_lead_time_hours >= 0, path.name
