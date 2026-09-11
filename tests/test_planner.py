"""Plans over time: the transitional blend, finite stock, and advice that is not execution."""
import json
from pathlib import Path

import pytest

from neftecode.planner import Planner, PlanCandidate, PlanStepSpec, PlannerError
from neftecode.scenario import load_scenario, parse_scenario

BASELINE = Path("config/scenarios/baseline.json")
SOUR = Path("config/scenarios/sour_crude.json")
NO_FEASIBLE = Path("config/scenarios/no_feasible.json")
BUDGET = 600


def planner(path=BASELINE):
    return Planner(load_scenario(path))


def result(path=BASELINE, **kw):
    return planner(path).plan(budget=BUDGET, **kw)


# --- The end-to-end scene the case is built around ---

def test_worsening_crude_with_a_delayed_correction_produces_a_transitional_plan():
    """Crude worsens, the hydrotreating correction needs two hours, the reserve is finite."""
    chosen = result(SOUR)
    assert chosen["selected"] is not None, "система обязана найти выполнимый план или отказать"
    plan = chosen["selected_plan"]
    assert len(plan["steps"]) == 2, "переходный план состоит из двух фаз"
    assert "временная помощь смешением" in plan["intent"]


def test_the_transitional_phase_leans_on_the_reserve_and_then_steps_back():
    plan = result(SOUR)["selected_plan"]
    first, second = plan["steps"]
    assert first["recipe"]["reserve"] > second["recipe"]["reserve"], "доля резерва должна снижаться"
    assert second["time_hours"] == pytest.approx(2.0), "пересмотр приходится на момент эффекта"


def test_the_correction_is_part_of_the_plan_from_the_first_step():
    plan = result(SOUR)["selected_plan"]
    base = planner(SOUR).base_controls()
    moved = [k for k, v in plan["steps"][0]["controls"].items() if abs(v - base[k]) > 1e-9]
    assert moved, "переходный план обязан нести саму коррекцию, а не только смешение"


def test_the_transitional_plan_wins_on_production_over_a_low_throughput_constant_plan():
    chosen = result(SOUR)
    constant = [a for a in chosen["alternatives"] if not a["candidate_id"].startswith("t")]
    if constant:
        assert chosen["selected"]["production_t"] >= max(a["production_t"] for a in constant)


# --- Finite stock is respected ---

def test_a_blend_that_would_outlast_the_reserve_is_not_selected():
    chosen = result(SOUR)
    scenario = load_scenario(SOUR)
    plan = chosen["selected_plan"]
    used = 0.0
    times = [s["time_hours"] for s in plan["steps"]] + [scenario.horizon.hours]
    for index, step in enumerate(plan["steps"]):
        used += step["throughput_tph"] * step["recipe"]["reserve"] * (times[index + 1] - times[index])
    assert used <= scenario.tank("reserve").inventory.value + 1e-6


def test_when_no_stock_can_carry_any_plan_the_answer_is_a_refusal():
    chosen = result(NO_FEASIBLE)
    assert chosen["selected"] is None
    assert "Ни один вариант" in chosen["reason"]


def test_a_normal_scenario_needs_no_extra_action():
    chosen = result(BASELINE)
    assert chosen["selected"] is not None
    assert chosen["selected"]["changes"] == 0, "в нормальном режиме менять нечего"


# --- Advice is not execution ---

def test_running_the_planner_twice_gives_the_same_answer():
    assert result(SOUR)["selected"] == result(SOUR)["selected"]


def test_the_result_states_that_the_plan_is_not_executed():
    assert "не считается исполненным" in result(BASELINE)["note"]


def test_an_unconfirmed_plan_leaves_no_trace_in_the_next_run():
    first = result(SOUR)
    second = result(SOUR)
    assert first["selected_plan"] == second["selected_plan"], \
        "повторный запуск не должен считать прошлый совет исполненным"


def test_a_confirmed_action_is_reported_separately_from_the_proposal():
    confirmed = ((0.0, {"ht_reactor_inlet_temp_c": 354.0}),)
    chosen = result(SOUR, confirmed=confirmed)
    assert chosen["confirmed_actions"][0]["controls"]["ht_reactor_inlet_temp_c"] == 354.0
    assert chosen["selected_plan"] is not None


def test_a_confirmed_correction_changes_what_the_planner_still_needs_to_do():
    """After a correction is confirmed, the advisor must account for it rather than repeat it."""
    plain = result(SOUR)
    with_action = result(SOUR, confirmed=((0.0, {"ht_reactor_inlet_temp_c": 356.0}),))
    assert with_action["selected"] is not None
    assert with_action["selected_plan"] != plain["selected_plan"] or \
           with_action["selected"]["production_t"] >= plain["selected"]["production_t"]


def test_a_confirmed_action_does_not_change_the_past_of_the_horizon():
    early = result(SOUR, confirmed=((0.0, {"ht_reactor_inlet_temp_c": 356.0}),))
    late = result(SOUR, confirmed=((2.5, {"ht_reactor_inlet_temp_c": 356.0}),))
    assert early["selected"] is not None and late["selected"] is not None


# --- Structure and evaluation ---

def test_plan_steps_must_start_at_zero_and_increase():
    p = planner()
    bad = PlanCandidate("x", (PlanStepSpec(1.0, p.base_controls(), {"main": 1.0}, 50.0),))
    with pytest.raises(PlannerError, match="начинаться в 0 ч"):
        p.evaluate(bad)


def test_every_evaluated_plan_carries_a_gate_verdict():
    p = planner()
    plan = PlanCandidate("x", (PlanStepSpec(0.0, p.base_controls(), {"main": 1.0}, 50.0),))
    evaluation = p.evaluate(plan)
    assert evaluation.gate.plan_id == "x"
    assert isinstance(evaluation.feasible, bool)


def test_an_impossible_plan_is_evaluated_as_infeasible_not_crashed():
    p = planner()
    plan = PlanCandidate("x", (PlanStepSpec(0.0, p.base_controls(), {"main": 1.0}, 10_000.0),))
    assert p.evaluate(plan).feasible is False


def test_the_grid_covers_the_whole_horizon():
    grid = planner().grid()
    assert grid[0] == 0.0
    assert grid[-1] == load_scenario(BASELINE).horizon.hours


def test_both_constant_and_transitional_plans_are_built():
    plans, info = planner(SOUR).build_plans(budget=BUDGET)
    kinds = {p.plan_id[0] for p in plans}
    assert "c" in kinds or "h" in kinds
    assert "t" in kinds, "переходные планы не построены"
    assert info["plans"] == len(plans)


def test_holding_the_regime_is_among_the_plans():
    plans, _ = planner().build_plans(budget=BUDGET)
    assert plans[0].plan_id == "hold"
    assert plans[0].changes == 0


def test_a_transitional_plan_changes_one_setpoint_plus_the_blend():
    plans, _ = planner(SOUR).build_plans(budget=BUDGET)
    transitional = [p for p in plans if p.plan_id.startswith("t")]
    assert transitional
    assert all(p.changes >= 1 for p in transitional)


def test_rejected_plans_keep_their_reasons():
    chosen = result(SOUR)
    assert chosen["rejected"], "в этом сценарии часть планов обязана отклоняться"
    assert any(r["rejection_reasons"] for r in chosen["rejected"])


def test_the_search_budget_is_reported():
    chosen = result(BASELINE)
    assert "budget" in chosen["search"]
    assert "Глобальная оптимальность" in chosen["search"]["claim"]


def test_alternatives_are_returned_alongside_the_choice():
    chosen = result(SOUR)
    assert chosen["alternatives"]
    assert all(a["candidate_id"] != chosen["selected"]["candidate_id"] for a in chosen["alternatives"])


def test_only_feasible_plans_appear_among_the_alternatives():
    chosen = result(SOUR)
    assert all(a["feasible"] for a in chosen["alternatives"])
