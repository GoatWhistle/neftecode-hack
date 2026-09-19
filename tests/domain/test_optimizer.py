import json
from pathlib import Path

import pytest

from neftecode.domain.advisory.entities import CheckResult, FAIL, GateResult, PASS, UNKNOWN
from neftecode.domain.advisory.optimizer import (DEFAULT_BUDGET, RANKING, Candidate, CandidateGenerator,
                                 Evaluation, OptimizerError, rank)
from neftecode.infrastructure.config.scenario import load_scenario, parse_scenario

BASELINE = Path("config/scenarios/baseline.json")


def generator(**kw):
    return CandidateGenerator(load_scenario(BASELINE), **kw)


def passing_gate(plan_id="p"):
    return GateResult(plan_id, (CheckResult("quality.sulfur_mgkg", PASS, 8.0, 10.0, 0.0),))


def failing_gate(plan_id="p"):
    return GateResult(plan_id, (CheckResult("quality.sulfur_mgkg", FAIL, 12.0, 10.0, 0.0,
                                            reason="выше предела"),))


def unknown_gate(plan_id="p"):
    return GateResult(plan_id, (CheckResult("quality.cetane_number", UNKNOWN, None, None, 0.0,
                                            reason="неизвестно"),))


def evaluation(candidate_id, gate, production=100.0, cost=1.0, severity=0.0, changes=1):
    candidate = Candidate(candidate_id, {"ht_reactor_inlet_temp_c": 348.0},
                          {"main": 1.0}, 100.0, 0.0, changes)
    return Evaluation(candidate, gate(candidate_id), production, cost, severity)



def test_holding_the_regime_is_the_first_candidate():
    candidates, _ = generator().generate()
    assert candidates[0].candidate_id == "hold"
    assert candidates[0].changes == 0


def test_the_hold_candidate_uses_the_scenario_setpoints():
    hold = generator().current()
    assert hold.controls["ht_reactor_inlet_temp_c"] == 348.0
    assert hold.additive_dose == 0.0


def test_a_feasible_hold_is_kept_when_no_change_earns_its_keep():
    hold = evaluation("hold", passing_gate, production=100.0, cost=1.00, changes=0)
    tweak = evaluation("c0001", passing_gate, production=100.0, cost=0.99)
    result = rank([hold, tweak], min_useful_gain=0.05)
    assert result["selected"]["candidate_id"] == "hold"
    assert "меньше минимального полезного" in result["reason"]


def test_a_clearly_cheaper_change_does_replace_the_hold():
    hold = evaluation("hold", passing_gate, production=100.0, cost=1.00, changes=0)
    better = evaluation("c0001", passing_gate, production=100.0, cost=0.70)
    assert rank([hold, better], min_useful_gain=0.05)["selected"]["candidate_id"] == "c0001"


def test_more_production_is_not_blocked_by_the_minimum_benefit_rule():
    hold = evaluation("hold", passing_gate, production=100.0, cost=1.00, changes=0)
    bigger = evaluation("c0001", passing_gate, production=140.0, cost=1.05)
    assert rank([hold, bigger], min_useful_gain=0.5)["selected"]["candidate_id"] == "c0001"



def test_an_infeasible_candidate_is_never_selected_however_attractive():
    good = evaluation("hold", passing_gate, production=50.0, cost=2.0, changes=0)
    tempting = evaluation("c0001", failing_gate, production=10_000.0, cost=0.01)
    result = rank([good, tempting])
    assert result["selected"]["candidate_id"] == "hold"
    assert "c0001" in [r["candidate_id"] for r in result["rejected"]]


def test_a_candidate_with_an_unknown_check_is_not_ranked():
    result = rank([evaluation("c0001", unknown_gate, production=9999.0, cost=0.0)])
    assert result["selected"] is None
    assert "Ни один вариант" in result["reason"]


def test_rejected_candidates_carry_their_reasons():
    result = rank([evaluation("hold", passing_gate, changes=0),
                   evaluation("c0001", failing_gate)])
    assert result["rejected"][0]["rejection_reasons"] == ["выше предела"]


def test_the_claim_states_that_weights_cannot_override_the_gate():
    result = rank([evaluation("hold", passing_gate, changes=0)])
    assert "не может выиграть никакими весами" in result["claim"]



def test_ranking_order_is_production_then_cost_then_severity():
    assert RANKING[:3] == ("-production_t", "cost_per_tonne", "severity_index")


def test_higher_production_wins_over_lower_cost():
    more = evaluation("c0001", passing_gate, production=120.0, cost=1.5)
    cheaper = evaluation("c0002", passing_gate, production=100.0, cost=0.5)
    assert rank([more, cheaper])["selected"]["candidate_id"] == "c0001"


def test_cost_breaks_the_tie_on_equal_production():
    a = evaluation("c0001", passing_gate, production=100.0, cost=1.5)
    b = evaluation("c0002", passing_gate, production=100.0, cost=0.5)
    assert rank([a, b])["selected"]["candidate_id"] == "c0002"


def test_severity_breaks_the_tie_on_equal_production_and_cost():
    a = evaluation("c0001", passing_gate, production=100.0, cost=1.0, severity=0.8)
    b = evaluation("c0002", passing_gate, production=100.0, cost=1.0, severity=0.2)
    assert rank([a, b])["selected"]["candidate_id"] == "c0002"


def test_the_result_does_not_depend_on_the_order_candidates_arrive_in():
    items = [evaluation(f"c{i:04d}", passing_gate, production=100.0, cost=1.0 + i * 0.1)
             for i in range(5)]
    assert rank(items)["selected"] == rank(list(reversed(items)))["selected"]


def test_a_missing_figure_sorts_last_rather_than_first():
    known = evaluation("c0001", passing_gate, production=100.0, cost=2.0)
    unknown_cost = evaluation("c0002", passing_gate, production=100.0, cost=None)
    assert rank([unknown_cost, known])["selected"]["candidate_id"] == "c0001"


def test_fewer_changes_break_a_complete_tie():
    many = evaluation("c0001", passing_gate, changes=3)
    few = evaluation("c0002", passing_gate, changes=1)
    assert rank([many, few])["selected"]["candidate_id"] == "c0002"



def test_generation_is_reproducible():
    first, _ = generator().generate()
    second, _ = generator().generate()
    assert [c.candidate_id for c in first] == [c.candidate_id for c in second]
    assert [c.to_dict() for c in first] == [c.to_dict() for c in second]


def test_no_duplicate_candidates_are_produced():
    candidates, _ = generator().generate()
    signatures = {(tuple(sorted(c.recipe.items())), c.throughput_tph,
                   tuple(sorted(c.controls.items())), c.additive_dose) for c in candidates}
    assert len(signatures) == len(candidates)


def test_the_whole_recipe_range_is_covered_not_only_its_start():
    candidates, info = generator().generate()
    fractions = {round(c.recipe.get("reserve", 0.0), 2) for c in candidates}
    assert 0.0 in fractions and 1.0 in fractions
    assert info["budget_exhausted"] is False


def test_each_layer_reports_whether_it_finished():
    _, info = generator().generate()
    assert [layer["layer"] for layer in info["layers"]] == \
           ["recipe_and_throughput", "control_moves", "additive"]
    assert all(layer["complete"] for layer in info["layers"])


def test_an_exhausted_budget_is_reported_honestly():
    _, info = generator(budget=20).generate()
    assert info["budget_exhausted"] is True
    assert info["generated"] <= 20
    assert "Глобальная оптимальность" in info["claim"]


def test_control_moves_change_one_setpoint_at_a_time():
    candidates, _ = generator().generate()
    base = candidates[0].controls
    for candidate in candidates:
        differing = [k for k, v in candidate.controls.items() if abs(v - base[k]) > 1e-9]
        assert len(differing) <= 1, "предлагается двигать несколько уставок сразу"


def test_every_proposed_setpoint_stays_inside_its_declared_range():
    scenario = load_scenario(BASELINE)
    candidates, _ = generator().generate()
    for candidate in candidates:
        for stage in scenario.stages.values():
            for name, spec in stage.controls.items():
                value = candidate.controls[name]
                assert spec["min"].value - 1e-9 <= value <= spec["max"].value + 1e-9


def test_every_proposed_dose_stays_within_the_expert_limit():
    limit = load_scenario(BASELINE).additive.max_dose_fraction.value
    candidates, _ = generator().generate()
    assert all(0.0 <= c.additive_dose <= limit + 1e-12 for c in candidates)


def test_every_recipe_is_a_composition():
    candidates, _ = generator().generate()
    for candidate in candidates:
        assert sum(candidate.recipe.values()) == pytest.approx(1.0)
        assert all(f >= -1e-9 for f in candidate.recipe.values())


def test_control_moves_can_be_switched_off():
    candidates, _ = generator().generate(allow_control_moves=False)
    base = candidates[0].controls
    assert all(c.controls == base for c in candidates)


def test_a_scenario_without_available_tanks_is_refused():
    raw = json.loads(BASELINE.read_text(encoding="utf-8"))
    for tank in raw["tanks"]:
        tank["available"] = True
    scenario = parse_scenario(raw)
    object.__setattr__(scenario, "tanks", ())
    with pytest.raises(OptimizerError, match="Нет доступных резервуаров"):
        CandidateGenerator(scenario).generate()


def test_default_budget_is_declared_not_hidden():
    assert generator().budget == DEFAULT_BUDGET
