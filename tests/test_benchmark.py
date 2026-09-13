"""Comparison with simple rules: identical conditions, no weak opponent, no dropped cases."""
import json
from pathlib import Path

import pytest

from neftecode.evaluation.benchmark import (ADVISOR, ADVISOR_NO_TERMINAL,
                                            ADVISOR_NO_TRANSITION, HOLD, STRATEGIES,
                                            THRESHOLD, Benchmark, compare)
from neftecode.application.use_cases.plan_operation import PlanOperation
from neftecode.infrastructure.config.scenario import load_scenario, parse_scenario

SCENARIOS = Path("config/scenarios")
BUDGET = 300


def loaded(name):
    path = SCENARIOS / f"{name}.json"
    return load_scenario(path), json.loads(path.read_text())


def bench(name):
    scenario, raw = loaded(name)
    return Benchmark(scenario, raw, BUDGET, parse_scenario)


def all_scenarios():
    return [loaded(p.stem) for p in sorted(SCENARIOS.glob("*.json"))]


@pytest.fixture(scope="module")
def report():
    return compare(all_scenarios(), budget=BUDGET, scenario_parser=parse_scenario)


def strategies(report, scenario_id):
    return next(r["strategies"] for r in report["scenarios"] if r["scenario_id"] == scenario_id)


# --- Identical conditions ---

def test_every_strategy_runs_on_every_scenario(report):
    for record in report["scenarios"]:
        assert set(record["strategies"]) == set(STRATEGIES)


def test_all_strategies_face_the_same_limits():
    """Different recipes produce different check ids, but the limits behind them are one set."""
    scenario, _ = loaded("sour_crude")
    planner = PlanOperation(scenario)
    hold = planner.evaluate(bench("sour_crude").hold_plan())
    threshold = planner.evaluate(bench("sour_crude").threshold_plan())

    def limits(evaluation):
        return {c.constraint_id: c.limit for c in evaluation.gate.checks
                if c.constraint_id.startswith("quality.") or c.constraint_id == "recipe.sum"}

    assert limits(hold) == limits(threshold), "стратегии проверяются разными пределами"
    assert limits(hold)["quality.sulfur_mgkg"] == scenario.product.limit_value("sulfur_mgkg")


def test_the_threshold_rule_gets_the_same_search_over_reserve_fractions():
    """A deliberately crippled opponent would prove nothing, so the rule may raise the reserve."""
    plan = bench("sour_crude").threshold_plan()
    reserve = plan.steps[0].recipe.get("reserve", 0.0)
    assert reserve > 0.0, "простое правило обязано иметь право поднять долю резерва"


def test_the_hold_strategy_reproduces_the_declared_current_regime():
    scenario, _ = loaded("baseline")
    plan = bench("baseline").hold_plan()
    assert plan.steps[0].throughput_tph == scenario.current_operation.throughput.value
    assert plan.steps[0].recipe["main"] == pytest.approx(scenario.current_operation.recipe["main"])
    assert plan.changes == 0


# --- The results themselves ---

def test_on_a_normal_scenario_nobody_wins_and_that_is_correct(report):
    normal = strategies(report, "baseline")
    assert all(not r.get("refused") and r["feasible"] for r in normal.values())
    assert normal[ADVISOR]["production_t"] == normal[HOLD]["production_t"]
    assert normal[ADVISOR]["changes"] == 0, "в нормальном режиме советчик не должен ничего менять"


def test_on_the_hard_scenario_only_the_advisor_stays_within_the_limits(report):
    hard = strategies(report, "sour_crude")
    assert hard[ADVISOR]["feasible"] is True
    assert hard[HOLD]["feasible"] is False
    assert hard[THRESHOLD]["feasible"] is False
    assert hard[HOLD]["violations"] > 0 and hard[THRESHOLD]["violations"] > 0


def test_the_advisor_pays_for_compliance_with_production(report):
    """Staying inside the limits costs output; that is the trade, and it is reported."""
    hard = strategies(report, "sour_crude")
    assert hard[ADVISOR]["production_t"] < hard[HOLD]["production_t"]


def test_where_nothing_is_feasible_the_advisor_refuses_and_the_simple_rules_violate(report):
    impossible = strategies(report, "no_feasible")
    assert impossible[ADVISOR].get("refused") is True
    assert impossible[HOLD]["feasible"] is False
    assert impossible[THRESHOLD]["feasible"] is False


def test_a_refusal_where_nothing_is_feasible_counts_as_a_correct_answer(report):
    note = next(w for w in report["wins"] if w["scenario_id"] == "no_feasible")
    assert "отказ — правильный ответ" in note["note"]


def test_wins_and_losses_are_both_reported(report):
    assert "wins" in report and "losses" in report
    assert any(w.get("beats") for w in report["wins"])


# --- Ablations show what the extra parts buy ---

def test_large_stock_removes_the_former_transition_advantage(report):
    hard = strategies(report, "sour_crude")
    assert hard[ADVISOR_NO_TRANSITION]["feasible"] is True
    assert hard[ADVISOR]["production_t"] == hard[ADVISOR_NO_TRANSITION]["production_t"]


def test_switching_off_the_terminal_rule_looks_better_and_that_is_stated(report):
    """Removing a safety rule raises the apparent number: exactly why the rule is there."""
    hard = strategies(report, "sour_crude")
    assert hard[ADVISOR_NO_TERMINAL]["production_t"] > hard[ADVISOR]["production_t"]
    ablation = next(a for a in report["ablations"]
                    if a["scenario_id"] == "sour_crude" and "остатка" in a["ablation"])
    assert "цена, а не недостаток" in ablation["effect"]


def test_each_ablation_reports_production_with_and_without(report):
    for ablation in report["ablations"]:
        if "production_with" in ablation:
            assert "production_without" in ablation
            assert ablation["effect"]


def test_ablations_cover_both_switched_off_parts(report):
    names = {a["ablation"] for a in report["ablations"]}
    assert "план во времени" in names
    assert "правило остатка на конце горизонта" in names


# --- Aggregation is honest ---

def test_every_scenario_enters_the_totals(report):
    for name in STRATEGIES:
        assert report["totals"][name]["scenarios"] == len(report["scenarios"])


def test_refusals_are_counted_not_hidden(report):
    assert report["totals"][ADVISOR]["refused"] >= 1
    assert report["totals"][ADVISOR]["feasible"] + report["totals"][ADVISOR]["refused"] \
           <= report["totals"][ADVISOR]["scenarios"]


def test_production_of_an_infeasible_run_is_not_credited(report):
    hard = strategies(report, "sour_crude")
    assert hard[HOLD]["feasible"] is False
    assert report["totals"][HOLD]["production_t"] < sum(
        s["strategies"][HOLD].get("production_t", 0.0) for s in report["scenarios"]
        if not s["strategies"][HOLD].get("refused"))


def test_the_aggregation_rule_forbids_dropping_bad_cases(report):
    assert "Исключать неудачные случаи" in report["aggregation"]


# --- The limits of the experiment are stated with it ---

def test_the_numbers_are_not_called_plant_savings(report):
    assert any("не являются экономией реального завода" in limit for limit in report["limits"])


def test_the_same_model_limitation_is_stated(report):
    assert any("той же модели, против которой он оптимизирует" in limit for limit in report["limits"])


def test_it_is_stated_that_no_weak_opponent_was_built(report):
    assert any("заведомо слабый соперник не строился" in limit for limit in report["limits"])


def test_the_small_scenario_set_is_admitted(report):
    assert any("Набор сценариев мал" in limit for limit in report["limits"])


def test_the_report_is_reproducible():
    first = compare(all_scenarios(), budget=BUDGET, scenario_parser=parse_scenario)
    second = compare(all_scenarios(), budget=BUDGET, scenario_parser=parse_scenario)
    assert first["totals"] == second["totals"]
    assert first["wins"] == second["wins"]


# --- Losses are looked for, not only wins ---

def test_the_comparison_is_not_limited_to_the_dimension_the_advisor_ranks_by():
    from neftecode.evaluation.benchmark import DIMENSIONS
    names = [label for _, label, _ in DIMENSIONS]
    assert "выпуск" in names
    assert {"стоимость на тонну", "расход резерва", "число изменений режима"} <= set(names)


def test_the_structural_bias_of_the_production_metric_is_stated(report):
    assert any("почти по построению" in limit for limit in report["limits"])


def test_real_losses_are_found_and_reported(report):
    """A scoreboard with no losses at all would be a rigged one."""
    assert report["losses"], "не найдено ни одного проигрыша: сравнение подозрительно"
    for loss in report["losses"]:
        assert loss["scenario_id"]
        assert loss.get("dimension") or loss.get("note")


def test_on_a_normal_regime_the_advisor_loses_on_cost_by_keeping_the_regime():
    """Not disturbing the plant costs money here, and the report says so instead of hiding it."""
    losses = compare(all_scenarios(), budget=BUDGET, scenario_parser=parse_scenario)["losses"]
    normal = [l for l in losses if l["scenario_id"] == "baseline"]
    assert normal, "советчик обязан проигрывать там, где сохраняет режим ради спокойствия"
    assert any(l["dimension"] == "стоимость на тонну" for l in normal)


def test_a_scenario_without_any_advantage_is_part_of_the_set(report):
    ample = strategies(report, "ample_reserve")
    assert ample[THRESHOLD]["feasible"] is True
    assert ample[ADVISOR]["production_t"] == ample[THRESHOLD]["production_t"]


def test_operator_disturbance_uses_the_current_recipe_as_baseline(report):
    ample = strategies(report, "ample_reserve")
    assert ample[ADVISOR]["changes"] == ample[THRESHOLD]["changes"] == 1
    normal = strategies(report, "baseline")
    assert normal[THRESHOLD]["changes"] == 1
    assert normal[ADVISOR]["changes"] == 0


def test_reserve_consumption_is_integrated_over_the_horizon():
    """Summing per-step rates would make a two-phase plan look twice as wasteful."""
    scenario, raw = loaded("sour_crude")
    benchmark = Benchmark(scenario, raw, BUDGET, parse_scenario)
    result = benchmark.run()["strategies"][ADVISOR]
    horizon = scenario.horizon.hours
    ceiling = scenario.tank("reserve").max_outflow.value * horizon
    assert result["reserve_used_t"] <= ceiling + 1e-6


def test_reserve_use_never_exceeds_the_stock_for_a_feasible_strategy(report):
    for record in report["scenarios"]:
        scenario = load_scenario(SCENARIOS / f"{record['scenario_id']}.json")
        stock = scenario.tank("reserve").inventory.value
        for name, result in record["strategies"].items():
            if result.get("refused") or not result["feasible"]:
                continue
            assert result["reserve_used_t"] <= stock + 1e-6, f"{record['scenario_id']}/{name}"
