import json
from pathlib import Path

import pytest

from neftecode.application.use_cases.plan_operation import PlanOperation, PlanCandidate, PlanStep, PlannerError
from neftecode.domain.production.inventory import InventoryLedger
from neftecode.infrastructure.config.scenario import load_scenario, parse_scenario

BASELINE = Path("config/scenarios/baseline.json")
SOUR = Path("config/scenarios/sour_crude.json")
NO_FEASIBLE = Path("config/scenarios/no_feasible.json")
BUDGET = 600


def planner(path=BASELINE):
    return PlanOperation(load_scenario(path))


def result(path=BASELINE, **kw):
    return planner(path).plan(budget=BUDGET, **kw)



def test_worsening_crude_with_a_delayed_correction_produces_a_transitional_plan():
    plans, _ = planner(SOUR).build_plans(BUDGET)
    transitions = [p for p in plans if len(p.steps) == 2]
    assert transitions


def test_the_transitional_phase_leans_on_the_reserve_and_then_steps_back():
    plans, _ = planner(SOUR).build_plans(BUDGET)
    plan = next(p for p in plans if len(p.steps) == 2)
    assert plan.steps[0].recipe["reserve"] > plan.steps[1].recipe["reserve"]
    assert plan.steps[1].time_hours == pytest.approx(2.0)


def test_the_correction_enters_the_filling_batch_after_the_process_lag():
    p = planner(SOUR)
    base = p.base_controls()
    controls = dict(base)
    controls["ht_reactor_inlet_temp_c"] += 8.0
    plan = PlanCandidate("response", (PlanStep(0.0, controls, {"main": .9, "reserve": .1}, 50.0),), 1)
    evaluation = p.evaluate(plan)
    sulfur = [c.observed for c in evaluation.gate.checks if c.constraint_id == "quality.sulfur_mgkg"]
    assert sulfur == pytest.approx([sulfur[0]] * len(sulfur)), \
        "качество уже паспортизованной сливаемой партии не меняется от нового притока"
    filling_sulfur = [
        next(t for t in frame["state"]["tanks"] if t["status"] == "filling")["properties"]["sulfur_mgkg"]
        for frame in evaluation.park["frames"]
    ]
    assert filling_sulfur[4] > filling_sulfur[0]
    assert filling_sulfur[5] < filling_sulfur[4], \
        "после двухчасовой задержки улучшение входит в новую наливаемую партию"


def test_the_transitional_plan_wins_on_production_over_a_low_throughput_constant_plan():
    chosen = result(SOUR)
    constant = [a for a in chosen["alternatives"] if not a["candidate_id"].startswith("t")]
    if constant:
        assert chosen["selected"]["production_t"] >= max(a["production_t"] for a in constant)



def test_a_blend_that_would_outrun_the_reserve_production_rate_is_not_selected():
    chosen = result(SOUR)
    scenario = load_scenario(SOUR)
    reserve = scenario.tank("reserve")
    assert reserve.on_demand is True, "резерв производится по необходимости, предел у него не запас, а темп"
    for step in chosen["selected_plan"]["steps"]:
        rate = step["throughput_tph"] * step["recipe"]["reserve"]
        assert rate <= reserve.max_outflow.value + 1e-6


def test_a_bad_passported_batch_needs_the_reserve_or_is_refused():
    corrected = result(SOUR)
    assert corrected["selected"] is not None
    assert any(step["recipe"]["reserve"] > 0 for step in corrected["selected_plan"]["steps"])
    assert corrected["selected"]["feasible"] is True

    raw = json.loads(SOUR.read_text(encoding="utf-8"))
    next(tank for tank in raw["tanks"] if tank["tank_id"] == "reserve")["available"] = False
    refused = PlanOperation(parse_scenario(raw)).plan(budget=BUDGET)
    assert refused["selected"] is None
    assert refused["rejected"], "некондиционная паспортизованная партия не должна пройти без резерва"


def test_when_no_stock_can_carry_any_plan_the_answer_is_a_refusal():
    chosen = result(NO_FEASIBLE)
    assert chosen["selected"] is None
    assert "Ни один вариант" in chosen["reason"]


def test_refusal_keeps_a_park_trajectory_that_explains_the_limit():
    from neftecode.application.use_cases.make_decision import MakeDecision
    decision = MakeDecision(load_scenario(NO_FEASIBLE)).decide(budget=BUDGET)
    assert decision["status"] == "refuse"
    assert decision["tank_park"]["model_version"] == "tank-park/1"
    assert decision["tank_park"]["frames"]
    assert decision["refusal"]["examples"]


def test_synthetic_phase_is_labelled_as_scenario_without_tau_scan():
    from neftecode.application.services.park_phase import ParkPhaseCheck
    raw = json.loads(BASELINE.read_text(encoding="utf-8"))
    scenario = parse_scenario(raw)
    check = ParkPhaseCheck(scenario, raw, parse_scenario, lambda _: None)
    result = check.evaluate("hold", "hold", budget=10)
    assert result["sensitive"] is False
    assert result["phase_source"] == "scenario"
    assert result["perturbations_declared"] == 0


def test_live_without_a_level_tag_refuses_when_the_plan_depends_on_tau():
    from neftecode.application.use_cases.make_decision import MakeDecision
    from neftecode.application.services.explain import explain
    from neftecode.application.services.tank_estimate import default_tank_estimate_factory
    raw = json.loads(BASELINE.read_text(encoding="utf-8"))
    raw["measurement_binding"] = {"tags": {}, "warnings": ["уровень парка не измерен"]}
    scenario = parse_scenario(raw)
    decision = MakeDecision(
        scenario, scenario_parser=parse_scenario,
        tank_estimate_factory=default_tank_estimate_factory,
    ).decide(budget=100, raw_scenario=raw)
    assert decision["status"] == "refuse"
    assert decision["refusal"]["kind"] == "tank_phase_sensitive"
    assert decision["tank_estimate"]["mode"] == "park_phase"
    assert decision["tank_estimate"]["failed_taus_h"]
    assert decision["gate"]["feasible"] is True
    assert decision["tank_park"]["model_version"] == "tank-park/1"
    explanation = explain(decision, scenario, {})
    assert explanation["kind"] == "tank_phase_sensitive"
    assert explanation["next_steps"][0]["kind"] == "measurement"
    assert "фактический уровень" in explanation["next_steps"][0]["need"]
    assert not any("None" in item["text"] for item in explanation["risk"]["items"])


def test_a_normal_scenario_needs_no_extra_action():
    chosen = result(BASELINE)
    assert chosen["selected"] is not None
    assert chosen["selected"]["changes"] == 0, "в нормальном режиме менять нечего"



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
    plain = result(SOUR)
    with_action = result(SOUR, confirmed=((0.0, {"ht_reactor_inlet_temp_c": 356.0}),))
    assert with_action["selected"] is not None
    assert with_action["selected_plan"] != plain["selected_plan"] or \
           with_action["selected"]["production_t"] >= plain["selected"]["production_t"]


def test_a_confirmed_action_does_not_change_the_past_of_the_horizon():
    early = result(SOUR, confirmed=((0.0, {"ht_reactor_inlet_temp_c": 356.0}),))
    late = result(SOUR, confirmed=((2.5, {"ht_reactor_inlet_temp_c": 356.0}),))
    assert early["selected"] is not None and late["selected"] is not None



def test_plan_steps_must_start_at_zero_and_increase():
    p = planner()
    bad = PlanCandidate("x", (PlanStep(1.0, p.base_controls(), {"main": 1.0}, 50.0),))
    with pytest.raises(PlannerError, match="начинаться в 0 ч"):
        p.evaluate(bad)


def test_every_evaluated_plan_carries_a_gate_verdict():
    p = planner()
    plan = PlanCandidate("x", (PlanStep(0.0, p.base_controls(), {"main": 1.0}, 50.0),))
    evaluation = p.evaluate(plan)
    assert evaluation.gate.plan_id == "x"
    assert isinstance(evaluation.feasible, bool)


def test_an_impossible_plan_is_evaluated_as_infeasible_not_crashed():
    p = planner()
    plan = PlanCandidate("x", (PlanStep(0.0, p.base_controls(), {"main": 1.0}, 10_000.0),))
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


def test_passported_draining_batch_keeps_t95_when_new_inflow_changes():
    p = planner()
    controls = p.base_controls()
    controls["avt_furnace_outlet_temp_c"] = 400.0
    plan = PlanCandidate("hot", (PlanStep(0.0, controls, {"main": 1.0}, 100.0),), 1)
    evaluation = p.evaluate(plan)
    values = [c.observed for c in evaluation.gate.checks if c.constraint_id == "quality.t95_c"]
    assert values[0] == pytest.approx(352.0)
    assert values == pytest.approx([352.0] * len(values))
    assert evaluation.park["model_version"] == "tank-park/1"


def test_small_passported_batch_is_blocked_when_it_runs_out_not_mixed_with_inflow():
    import dataclasses
    p = planner()
    tanks = {k: dataclasses.replace(v, inventory_t=10.0, properties={**v.properties, "t95_c": 359.0})
             for k, v in __import__("neftecode.domain.production.inventory", fromlist=["initial_state"]).initial_state(p.scenario).items()}
    controls = p.base_controls()
    controls["avt_furnace_outlet_temp_c"] = 400.0
    plan = PlanCandidate("hot-small", (PlanStep(0.0, controls, {"main": 1.0}, 10.0),), 1)
    evaluation = p.evaluate(plan, initial_tanks=tanks)
    assert not evaluation.feasible
    assert any(c.constraint_id == "park.transition" and c.status == "fail"
               for c in evaluation.gate.checks)
    assert not any(c.constraint_id == "quality.t95_c" and c.status == "fail"
                   for c in evaluation.gate.checks)


def test_park_trajectory_is_the_source_for_gate_and_output():
    p = planner()
    plan = PlanCandidate("park-ok", (PlanStep(0.0, p.base_controls(), {"main": 1.0}, 100.0),), 0)
    evaluation = p.evaluate(plan)
    assert evaluation.feasible
    assert evaluation.park["model_version"] == "tank-park/1"
    assert abs(evaluation.park["terminal"]["balance_error_t"]) < 1e-9
    assert any(check.constraint_id == "park.balance" for check in evaluation.gate.checks)


def test_per_tank_nominal_drain_limit_changes_admissibility():
    p = planner()
    plan = PlanCandidate("park-too-fast", (PlanStep(0.0, p.base_controls(), {"main": 1.0}, 180.0),), 1)
    evaluation = p.evaluate(plan)
    assert not evaluation.feasible
    assert any(check.constraint_id == "park.transition" and check.status == "fail"
               and "не хватает" in check.reason for check in evaluation.gate.checks)


def test_long_park_schedule_keeps_balance_and_does_not_lose_boundary_events():
    import dataclasses
    short = load_scenario(BASELINE)
    extended = dataclasses.replace(short, horizon=dataclasses.replace(short.horizon, hours=75.0))
    p = PlanOperation(extended)
    plan = PlanCandidate("park-long", (PlanStep(0.0, p.base_controls(), {"main": 1.0}, 100.0),), 0)
    evaluation = p.evaluate(plan)
    frames = evaluation.park["frames"]
    assert len(frames) == len(p.grid())
    assert all(abs(frame["state"]["balance_error_t"]) < 1e-8 for frame in frames)
    assert any(frame["inflow_by_tank"] for frame in frames[1:])
    assert any(frame["outflow_by_tank"] for frame in frames[1:])
    batches = {tank["batch_id"] for frame in frames for tank in frame["state"]["tanks"]
               if tank["batch_id"] is not None}
    assert len(batches) > extended.tank_park.tank_count, \
        "за длинный горизонт должен завершиться хотя бы один полный оборот и начаться новая партия"


def with_lead(path: Path, lead_hours: float):
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    for tank in raw["tanks"]:
        if tank.get("on_demand"):
            tank["production_lead_time_hours"]["value"] = lead_hours
    return parse_scenario(raw)


def test_no_generated_plan_draws_the_on_demand_component_before_it_can_be_made():
    for lead in (0.5, 1.0, 2.5, 3.0):
        scenario = with_lead(SOUR, lead)
        planner = PlanOperation(scenario)
        plans, _ = planner.build_plans(BUDGET)
        grid = planner.grid()
        properties = {t: planner.inflow_properties(t, ()) for t in grid}
        for plan in plans:
            steps = [(t, planner._active_step(plan, t).recipe,
                      planner._active_step(plan, t).throughput_tph) for t in grid]
            stock = InventoryLedger(scenario).run_plan(steps, properties)
            early = [reason for entry in stock["timeline"] for reason in entry["reasons"]
                     if "произвести можно" in reason]
            assert not early, (lead, plan.plan_id, early)


def test_a_positive_preparation_time_delays_the_component_instead_of_forbidding_it():
    scenario = with_lead(SOUR, 1.0)
    plans, _ = PlanOperation(scenario).build_plans(BUDGET)
    by_id = {p.plan_id: p for p in plans}
    hold = by_id["hold"]
    assert len(hold.steps) == 2
    assert hold.steps[0].recipe["reserve"] == 0.0
    assert hold.steps[1].time_hours == pytest.approx(1.0)
    assert hold.steps[1].recipe["reserve"] > 0.0


def test_a_preparation_time_past_the_horizon_drops_the_component_where_a_blend_remains():
    scenario = with_lead(SOUR, 4.0)
    planner = PlanOperation(scenario)
    plans, _ = planner.build_plans(BUDGET)
    survivors = []
    for plan in plans:
        for step in plan.steps:
            if step.recipe.get("reserve", 0.0) > 0.0:
                survivors.append(plan)
                break
    assert all(abs(p.steps[0].recipe["reserve"] - 1.0) < 1e-9 for p in survivors)
    for plan in survivors:
        assert not planner.evaluate(plan).gate.feasible, plan.plan_id


def test_zero_preparation_time_keeps_every_plan_a_single_constant_step():
    plans, _ = PlanOperation(with_lead(SOUR, 0.0)).build_plans(BUDGET)
    singles = [p for p in plans if p.plan_id.startswith("c") or p.plan_id == "hold"]
    assert singles and all(len(p.steps) == 1 for p in singles)
