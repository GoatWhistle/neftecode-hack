from pathlib import Path
from types import SimpleNamespace

import pytest

from neftecode.domain.advisory.tradeoff import dominates, tradeoff_map


def ev(cid, production, cost, severity, changes=1, controls=None):
    candidate = SimpleNamespace(candidate_id=cid, controls=controls or {"t": 350.0}, recipe={"main": 1.0},
                                throughput_tph=100.0, additive_dose=0.0, changes=changes)
    return SimpleNamespace(candidate=candidate, production_t=production, cost_per_tonne=cost,
                           severity_index=severity)


def by_id(result):
    return {p["candidate_id"]: p for p in result["points"]}


def test_dominance_needs_no_worse_everywhere_and_strictly_better_somewhere():
    a = {"production_t": 300.0, "cost_per_tonne": 1.0, "severity_index": 0.1}
    assert dominates(a, {**a, "cost_per_tonne": 1.1})
    assert not dominates(a, dict(a))
    assert not dominates(a, {**a, "production_t": 310.0})
    assert not dominates({**a, "cost_per_tonne": 1.2, "severity_index": 0.0}, a)
    assert not dominates(a, {**a, "cost_per_tonne": 1.0 + 1e-9})


def test_front_contains_non_dominated_and_marks_dominated_with_a_dominator():
    pool = [ev("hold", 300, 1.1, 0.5, 0), ev("c1", 300, 1.0, 0.5), ev("c2", 300, 1.2, 0.1), ev("c3", 250, 1.3, 0.6)]
    result = tradeoff_map(pool, "c1")
    points = by_id(result)
    assert {k for k, p in points.items() if p["on_front"]} == {"c1", "c2"}
    assert points["hold"]["dominated_by"] == "c1" and points["c3"]["on_front"] is False
    assert result["selected_id"] == "c1" and result["selected_on_front"] is True and result["selection_note"] is None
    assert result["pool"]["front"] == 2 and result["pool"]["dominated"] == 2


def test_equal_plans_do_not_dominate_each_other_and_are_grouped():
    pool = [ev("a", 300, 1.0, 0.2), ev("b", 300, 1.0, 0.2), ev("c", 300, 1.0, 0.2 + 1e-9)]
    result = tradeoff_map(pool, "b")
    assert result["pool"]["front"] == 3 and result["pool"]["front_distinct"] == 1
    assert len(result["points"]) == 1 and result["points"][0]["equivalent_count"] == 2
    assert result["points"][0]["candidate_id"] == "b" and result["points"][0]["selected"] is True


def test_empty_and_single_pools():
    empty = tradeoff_map([], None)
    assert empty["status"] == "empty" and empty["points"] == [] and empty["pool"]["front"] == 0
    single = tradeoff_map([ev("hold", 300, 1.0, 0.0, 0)], "hold")
    assert single["status"] == "ok" and single["pool"]["front_distinct"] == 1
    assert single["hold"]["admissible"] is True


def test_plans_with_unknown_numbers_are_excluded_with_a_reason_not_zeroed():
    pool = [ev("known", 300, 1.0, 0.1), ev("nosev", 300, 0.5, None), ev("nocost", 300, None, 0.0),
            ev("nan", 300, float("nan"), 0.0)]
    result = tradeoff_map(pool, "known")
    assert [p["candidate_id"] for p in result["points"]] == ["known"]
    assert result["pool"]["excluded_unknown_count"] == 3
    assert {e["candidate_id"]: e["missing"] for e in result["pool"]["excluded_unknown"]}["nosev"] == ["severity_index"]
    assert tradeoff_map([ev("x", 300, 1.0, None)], "x")["status"] == "unknown_metrics"


def test_selection_by_policy_is_reported_as_dominated_not_recoloured():
    pool = [ev("hold", 300, 1.1, 0.0, 0), ev("c1", 300, 1.05, 0.0)]
    result = tradeoff_map(pool, "hold", selection_reason="Выигрыш меньше минимального полезного")
    assert result["selected_on_front"] is False
    assert by_id(result)["hold"]["on_front"] is False and by_id(result)["hold"]["selected"] is True
    assert "правилу" in result["selection_note"] and "Выигрыш меньше" in result["selection_note"]


def test_inadmissible_hold_is_reported_separately_and_stress_belongs_to_the_selected_plan_only():
    pool = [ev("c1", 300, 1.0, 0.1), ev("c2", 300, 1.2, 0.0)]
    result = tradeoff_map(pool, "c1", hold_note="Нарушен предел серы", stress_checked_id="c1",
                          robustness={"held": 5})
    assert result["hold"] == {"id": "hold", "admissible": False, "note": "Нарушен предел серы"}
    points = by_id(result)
    assert points["c1"]["stress_checked"] is True and points["c1"]["robustness"] == {"held": 5}
    assert points["c2"]["stress_checked"] is False and points["c2"]["gate_passed"] is True
    assert "только для выбранного плана" in result["stress_scope"]


def test_many_dominated_points_are_sampled_but_selected_and_hold_stay():
    pool = [ev("hold", 300, 2.0, 0.9, 0)] + [ev(f"c{i}", 300, 1.5 + i * 0.001, 0.5) for i in range(200)]
    pool.append(ev("best", 300, 1.0, 0.0))
    result = tradeoff_map(pool, "c77")
    assert result["pool"]["points_truncated"] is True and len(result["points"]) <= 62
    assert {"hold", "c77", "best"} <= set(by_id(result))


def test_moves_are_reported_against_hold():
    pool = [ev("hold", 300, 1.1, 0.0, 0, controls={"t": 350.0, "f": 100.0}),
            ev("c1", 300, 1.0, 0.0, controls={"t": 352.0, "f": 100.0})]
    move = by_id(tradeoff_map(pool, "c1"))["c1"]["moves"]
    assert move == [{"name": "t", "from": 350.0, "to": 352.0}]
