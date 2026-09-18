"""The changeable demo: an admissible edit reaches the calculation, an inadmissible one is refused."""
import copy
import json
from pathlib import Path

import pytest

from neftecode.bootstrap import run_demo_decision
from neftecode.infrastructure.config.trust_rules import load_trust_rules
from neftecode.presentation.demo import (CHANGES, SOURCE_FAULTS, Demo, DemoError, apply_change,
                                         apply_source_failure, healthy_state, scenes)

BASELINE = Path("config/scenarios/baseline.json")
BUDGET = 300
TRUST_CFG, TRUST_ORIGIN = load_trust_rules(Path("."), Path("artifacts"))


@pytest.fixture(scope="module")
def demo():
    return Demo.from_path(BASELINE, run_demo_decision, TRUST_CFG, budget=BUDGET, trust_origin=TRUST_ORIGIN)


def raw():
    return json.loads(BASELINE.read_text())


# --- A change reaches the calculation, it does not switch a canned answer ---

def test_worse_crude_changes_the_decision(demo):
    normal = demo.run()
    worse = demo.run([{"change": "crude_sulfur_wt_pct", "value": 2.1}])
    assert normal["decision"]["decision_id"] != worse["decision"]["decision_id"]


def test_a_change_moves_the_computed_quality_not_only_the_text(demo):
    normal = demo.run()
    worse = demo.run([{"change": "crude_sulfur_wt_pct", "value": 1.9}])

    def sulfur(result):
        checks = [c for c in result["decision"]["gate"]["checks"]
                  if c["constraint_id"] == "quality.sulfur_mgkg" and c["observed"] is not None]
        return max(c["observed"] for c in checks)

    assert sulfur(worse) > sulfur(normal), "изменение не дошло до расчёта"


def test_removing_a_tank_changes_what_is_proposed(demo):
    with_reserve = demo.run()
    without = demo.run([{"change": "tank_available", "value": False, "target": "reserve"}])
    assert without["decision"]["decision_id"] != with_reserve["decision"]["decision_id"]


def test_lowering_the_stock_reaches_the_inventory_check(demo):
    plenty = demo.run([{"change": "tank_inventory", "value": 600.0, "target": "reserve"}])
    scarce = demo.run([{"change": "tank_inventory", "value": 5.0, "target": "reserve"}])
    assert plenty["screen"]["inventories"]["reserve"] == 600.0
    assert scarce["screen"]["inventories"]["reserve"] == 5.0


def test_a_tighter_product_limit_changes_the_answer(demo):
    loose = demo.run()
    tight = demo.run([{"change": "product_t95_c", "value": 300.0}])
    assert tight["decision"]["status"] != loose["decision"]["status"] or \
           tight["decision"]["decision_id"] != loose["decision"]["decision_id"]


def test_changing_the_throughput_reaches_the_plan(demo):
    slower = demo.run([{"change": "throughput_tph", "value": 60.0}])
    assert slower["decision"]["selected_plan"]["steps"][0]["throughput_tph"] <= 60.0


def test_several_changes_apply_together(demo):
    result = demo.run([{"change": "crude_sulfur_wt_pct", "value": 1.8},
                       {"change": "tank_inventory", "value": 40.0, "target": "reserve"}])
    assert result["ok"] is True
    assert len(result["applied"]) == 2


def test_the_result_states_there_are_no_prepared_answers(demo):
    assert "заранее заготовленных ответов здесь нет" in demo.run()["note"]


# --- Inadmissible changes are refused, not repaired ---

def test_weakening_the_hard_sulfur_limit_is_refused(demo):
    result = demo.run([{"change": "product_sulfur_mgkg", "value": 20.0}])
    assert result["rejected"] is True
    assert "мягче требования ТЗ" in result["reason"]
    assert result["screen"]["state"] == "error"


def test_a_negative_stock_is_refused(demo):
    result = demo.run([{"change": "tank_inventory", "value": -100.0, "target": "reserve"}])
    assert result["rejected"] is True
    assert "отрицательное" in result["reason"].lower()


def test_making_every_tank_unavailable_is_refused(demo):
    result = demo.run([{"change": "tank_available", "value": False, "target": t}
                       for t in ("main", "reserve", "light")])
    assert result["rejected"] is True


def test_an_unsupported_change_is_refused_by_name():
    with pytest.raises(DemoError, match="не умеет менять"):
        apply_change(raw(), "погода", 1.0)


def test_a_tank_change_without_a_target_is_refused():
    with pytest.raises(DemoError, match="нужно указать резервуар"):
        apply_change(raw(), "tank_inventory", 100.0)


def test_an_unknown_tank_is_refused():
    with pytest.raises(DemoError, match="не описан"):
        apply_change(raw(), "tank_inventory", 100.0, target="ghost")


def test_an_inadmissible_change_is_not_silently_repaired(demo):
    result = demo.run([{"change": "product_sulfur_mgkg", "value": 20.0}])
    assert "не исправлено молча" in result["note"]


# --- Injected faults are labelled as injections ---

def test_every_declared_fault_is_applicable():
    for fault in SOURCE_FAULTS:
        apply_source_failure(healthy_state(), fault)


def test_an_injected_fault_is_marked_as_a_model_injection():
    state = apply_source_failure(healthy_state(), "frozen_pak")
    assert state["origin"] == "injected_source_failure"
    assert "не наблюдение из данных" in state["injection"]


def test_a_healthy_state_carries_no_injection_label():
    state = apply_source_failure(healthy_state(), "healthy")
    assert "injection" not in state


def test_an_unknown_fault_is_refused():
    with pytest.raises(DemoError, match="Неизвестный отказ"):
        apply_source_failure(healthy_state(), "молния")


def test_a_frozen_analyser_is_visible_on_the_screen(demo):
    result = demo.run(fault="frozen_pak")
    pak = next(s for s in result["screen"]["sources"] if s["name"] == "ПАК")
    assert pak["usable"] is False
    assert any("зависан" in r for r in pak["reasons"])


def test_broken_sources_lead_to_a_refusal(demo):
    result = demo.run(fault="both_broken")
    assert result["decision"]["status"] == "refuse"
    assert result["screen"]["state"] == "refusal"


def test_an_unavailable_tank_change_is_labelled_as_an_injection():
    altered = apply_change(raw(), "tank_available", False, target="reserve")
    reserve = next(t for t in altered["tanks"] if t["tank_id"] == "reserve")
    assert "инъекция условий демонстрации" in reserve["note"]


# --- The original is always recoverable ---

def test_the_original_scenario_is_never_mutated(demo):
    before = copy.deepcopy(demo.raw)
    demo.run([{"change": "crude_sulfur_wt_pct", "value": 3.0},
              {"change": "tank_available", "value": False, "target": "reserve"}])
    assert demo.raw == before


def test_reset_returns_the_original_conditions(demo):
    demo.run([{"change": "crude_sulfur_wt_pct", "value": 3.0}])
    assert demo.reset().run()["decision"]["decision_id"] == demo.run()["decision"]["decision_id"]


def test_running_the_same_change_twice_gives_the_same_result(demo):
    change = [{"change": "crude_sulfur_wt_pct", "value": 1.7}]
    assert demo.run(change)["decision"]["decision_id"] == demo.run(change)["decision"]["decision_id"]


# --- The required scenes ---

def test_the_required_scenes_are_all_present():
    names = [s["name"] for s in scenes(BASELINE)]
    assert any("Нормальный" in n for n in names)
    assert any("Ухудшение" in n for n in names)
    assert any("анализатор" in n for n in names)
    assert any("лаборатория" in n for n in names)


def test_every_scene_produces_a_renderable_screen(demo):
    for scene in scenes(BASELINE):
        result = demo.run(scene["changes"], scene["fault"])
        assert result["screen"]["state"] in ("decision", "refusal")


def test_the_scenes_cover_normal_risk_bad_data_and_no_solution(demo):
    statuses = {demo.run(s["changes"], s["fault"])["decision"]["status"]
                for s in scenes(BASELINE) if not demo.run(s["changes"], s["fault"])["rejected"]}
    assert "hold" in statuses, "нет сцены нормального режима"
    assert "refuse" in statuses, "нет сцены без надёжного решения"
    assert len(statuses) >= 3


def test_the_change_catalogue_is_declared():
    assert "crude_sulfur_wt_pct" in CHANGES
    assert "tank_available" in CHANGES
    assert all(isinstance(v, tuple) and len(v) == 2 for v in CHANGES.values())
