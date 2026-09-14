"""Blending: sulfur by mass balance, other properties by a declared rule, unknown preserved."""
import json
from pathlib import Path

import pytest

from neftecode.domain.production.blending import (MASS_BALANCE, SCENARIO_LINEAR, UNKNOWN, BlendError, Blender,
                                check_recipe, mass_balance)
from neftecode.infrastructure.config.scenario import load_scenario, parse_scenario

BASELINE = Path("config/scenarios/baseline.json")


def blender(path=BASELINE):
    return Blender(load_scenario(path))


# --- A recipe must be a real composition ---

def test_fractions_must_sum_to_one():
    with pytest.raises(BlendError, match="дают"):
        check_recipe({"main": 0.8, "reserve": 0.1})


def test_negative_fraction_is_refused():
    with pytest.raises(BlendError, match="Отрицательная доля"):
        check_recipe({"main": 1.2, "reserve": -0.2})


def test_empty_recipe_is_refused():
    with pytest.raises(BlendError, match="пуст"):
        check_recipe({})


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_non_finite_fraction_is_refused(value):
    with pytest.raises(BlendError, match="конечным числом"):
        check_recipe({"main": value})


def test_recipe_naming_an_undescribed_tank_is_refused():
    with pytest.raises(BlendError, match="не описанные резервуары"):
        blender().blend({"main": 0.5, "ghost": 0.5}, 100.0)


# --- Sulfur is a genuine mass balance ---

def test_pure_component_keeps_its_own_sulfur():
    result = blender().blend({"main": 1.0}, 100.0)
    assert result.qualities["sulfur_mgkg"] == pytest.approx(8.0)
    assert result.methods["sulfur_mgkg"] == MASS_BALANCE


def test_blend_sulfur_matches_hand_computation():
    result = blender().blend({"main": 0.9, "reserve": 0.1}, 100.0)
    assert result.qualities["sulfur_mgkg"] == pytest.approx(0.9 * 8.0 + 0.1 * 2.0)


def test_extreme_fractions_reach_the_pure_component_values():
    assert blender().blend({"main": 1.0, "reserve": 0.0}, 100.0).qualities["sulfur_mgkg"] == pytest.approx(8.0)
    assert blender().blend({"main": 0.0, "reserve": 1.0}, 100.0).qualities["sulfur_mgkg"] == pytest.approx(2.0)


def test_blend_sulfur_lies_between_the_components():
    result = blender().blend({"main": 0.5, "reserve": 0.5}, 100.0)
    assert 2.0 < result.qualities["sulfur_mgkg"] < 8.0


def test_mass_balance_of_an_unused_component_does_not_make_the_blend_unknown():
    assert mass_balance({"a": 1.0, "b": 0.0}, {"a": 5.0, "b": None}) == pytest.approx(5.0)


def test_one_unknown_used_component_makes_the_balance_unknown():
    assert mass_balance({"a": 0.5, "b": 0.5}, {"a": 5.0, "b": None}) is None


# --- Mass and composition agree ---

def test_component_masses_sum_to_the_produced_mass():
    result = blender().blend({"main": 0.7, "reserve": 0.3}, 120.0, hours=2.0)
    assert sum(result.component_mass_t.values()) == pytest.approx(240.0)
    assert result.total_mass_t == pytest.approx(240.0)


def test_zero_throughput_produces_nothing_without_failing():
    result = blender().blend({"main": 1.0}, 0.0)
    assert result.total_mass_t == 0.0
    assert result.qualities["sulfur_mgkg"] == pytest.approx(8.0)


def test_negative_throughput_is_refused():
    with pytest.raises(BlendError, match="неотрицательным"):
        blender().blend({"main": 1.0}, -10.0)


# --- T95 and cetane are not silently treated as sulfur ---

def test_other_properties_declare_a_different_rule_than_sulfur():
    result = blender().blend({"main": 0.9, "reserve": 0.1}, 100.0)
    assert result.methods["sulfur_mgkg"] == MASS_BALANCE
    assert result.methods["t95_c"] == SCENARIO_LINEAR
    assert result.methods["cetane_number"] == SCENARIO_LINEAR


def test_the_non_linearity_of_those_properties_is_stated_in_the_notes():
    result = blender().blend({"main": 0.9, "reserve": 0.1}, 100.0)
    assert any("нелинейно" in note for note in result.notes)


# --- Unknown stays unknown ---

def test_component_without_cetane_makes_the_blend_cetane_unknown():
    result = blender().blend({"main": 0.8, "light": 0.2}, 100.0)
    assert result.qualities["cetane_number"] is None
    assert result.methods["cetane_number"] == UNKNOWN
    assert "cetane_number" in result.unknown_qualities()


def test_unknown_critical_property_is_not_a_pass():
    b = blender()
    checks = b.meets_spec(b.blend({"main": 0.8, "light": 0.2}, 100.0))
    assert checks["cetane_number"]["status"] == UNKNOWN
    assert checks["cetane_number"]["status"] != "pass"


def test_unknown_property_names_the_component_responsible():
    result = blender().blend({"main": 0.8, "light": 0.2}, 100.0)
    assert any("light" in note for note in result.notes)


def test_a_missing_limit_is_reported_as_unknown_not_as_satisfied():
    raw = json.loads(BASELINE.read_text())
    raw["product"]["t95_c"] = None
    b = Blender(parse_scenario(raw))
    checks = b.meets_spec(b.blend({"main": 1.0}, 100.0))
    assert checks["t95_c"]["status"] == UNKNOWN
    assert "не задан" in checks["t95_c"]["reason"]


# --- Specification comparison ---

def test_compliant_blend_passes_every_known_check():
    b = blender()
    checks = b.meets_spec(b.blend({"main": 0.9, "reserve": 0.1}, 100.0))
    assert {c["status"] for c in checks.values()} == {"pass"}
    assert checks["sulfur_mgkg"]["margin"] > 0


def test_sulfur_above_the_limit_fails_with_a_reason():
    b = blender(Path("config/scenarios/no_feasible.json"))
    checks = b.meets_spec(b.blend({"main": 1.0}, 100.0))
    assert checks["sulfur_mgkg"]["status"] == "fail"
    assert "нарушает предел" in checks["sulfur_mgkg"]["reason"]


def test_cetane_is_a_minimum_not_a_maximum():
    b = blender()
    checks = b.meets_spec(b.blend({"main": 1.0}, 100.0))
    assert checks["cetane_number"]["direction"] == "min"
    assert checks["sulfur_mgkg"]["direction"] == "max"


# --- The additive ---

def test_additive_raises_cetane_by_the_declared_rule():
    b = blender()
    without = b.blend({"main": 1.0}, 100.0).qualities["cetane_number"]
    with_dose = b.blend({"main": 1.0}, 100.0, additive_dose=0.02).qualities["cetane_number"]
    assert with_dose == pytest.approx(without + 1.2 * 0.02 * 100)


def test_additive_adds_its_own_mass_on_top_of_the_components():
    result = blender().blend({"main": 1.0}, 100.0, hours=1.0, additive_dose=0.02)
    assert result.additive_mass_t == pytest.approx(2.0)
    assert result.total_mass_t == pytest.approx(102.0)
    assert sum(result.component_mass_t.values()) == pytest.approx(100.0)


def test_additive_lowers_sulfur_only_by_dilution_and_says_so():
    b = blender()
    plain = b.blend({"main": 1.0}, 100.0).qualities["sulfur_mgkg"]
    dosed = b.blend({"main": 1.0}, 100.0, additive_dose=0.02)
    assert dosed.qualities["sulfur_mgkg"] == pytest.approx(plain * 100.0 / 102.0)
    assert any("удаление серы" in note for note in dosed.notes)


def test_dose_above_the_scenario_limit_is_refused():
    with pytest.raises(BlendError, match="превышает заданный предел"):
        blender().blend({"main": 1.0}, 100.0, additive_dose=0.05)


def test_negative_dose_is_refused():
    with pytest.raises(BlendError, match="неотрицательной"):
        blender().blend({"main": 1.0}, 100.0, additive_dose=-0.01)


def test_zero_dose_leaves_the_blend_untouched():
    b = blender()
    assert b.blend({"main": 1.0}, 100.0, additive_dose=0.0).to_dict() == \
           b.blend({"main": 1.0}, 100.0).to_dict()


def test_dose_without_a_described_additive_is_refused():
    raw = json.loads(BASELINE.read_text())
    raw["additive"] = None
    with pytest.raises(BlendError, match="не описывает присадку"):
        Blender(parse_scenario(raw)).blend({"main": 1.0}, 100.0, additive_dose=0.01)


def test_additive_without_a_dose_response_gives_unknown_not_improvement():
    raw = json.loads(BASELINE.read_text())
    raw["additive"]["cetane_gain_per_dose_pct"] = None
    b = Blender(parse_scenario(raw))
    result = b.blend({"main": 1.0}, 100.0, additive_dose=0.02)
    assert result.qualities["cetane_number"] is None
    assert any("не задана" in note for note in result.notes)


def test_additive_effect_is_labelled_as_an_assumption():
    result = blender().blend({"main": 1.0}, 100.0, additive_dose=0.01)
    assert any("сценарное допущение" in note for note in result.notes)


def test_scenario_cannot_declare_the_additive_removes_sulfur():
    raw = json.loads(BASELINE.read_text())
    raw["additive"]["affects"] = ["sulfur_mgkg"]
    from neftecode.infrastructure.config.scenario import ScenarioError
    with pytest.raises(ScenarioError, match="удаление серы"):
        parse_scenario(raw)


# --- Density: volume additivity and a two-sided product limit ---

from neftecode.domain.shared.primitives import volume_additive_density  # noqa: E402
from neftecode.domain.production.state import TankState  # noqa: E402


def test_density_blends_by_volume_not_by_mass():
    rho = volume_additive_density({"a": 50.0, "b": 50.0}, {"a": 800.0, "b": 900.0})
    assert rho == pytest.approx(100.0 / (50 / 800 + 50 / 900))
    assert rho < 850.0, "линейное среднее по массе переоценило бы плотность"


def test_unknown_density_of_a_used_component_makes_the_blend_unknown():
    assert volume_additive_density({"a": 1.0, "b": 1.0}, {"a": 836.0, "b": None}) is None
    assert volume_additive_density({"a": 1.0, "b": 0.0}, {"a": 836.0, "b": None}) == pytest.approx(836.0)


def test_shipped_blend_carries_density_and_checks_both_limits():
    from neftecode.domain.production.blending import Blender, VOLUME_ADDITIVE
    from neftecode.infrastructure.config.scenario import load_scenario
    blender = Blender(load_scenario(Path("config/scenarios/baseline.json")))
    ok = blender.blend({"main": 0.9, "reserve": 0.1}, 100.0)
    assert ok.methods["density_kgm3"] == VOLUME_ADDITIVE
    assert 832.0 < ok.qualities["density_kgm3"] < 836.1
    spec = blender.meets_spec(ok)
    assert spec["density_min_kgm3"]["status"] == "pass" and spec["density_max_kgm3"]["status"] == "pass"
    light = blender.meets_spec(blender.blend({"light": 1.0}, 10.0))
    assert light["density_min_kgm3"]["status"] == "fail"


def test_inflow_mixes_density_by_volume():
    tank = TankState("main", True, 100.0, {"sulfur_mgkg": 8.0, "t95_c": 350.0, "cetane_number": 51.0,
                                            "density_kgm3": 800.0})
    mixed = tank.mix_in(100.0, {"sulfur_mgkg": 8.0, "t95_c": 350.0, "cetane_number": 51.0,
                                "density_kgm3": 900.0})
    assert mixed.properties["density_kgm3"] == pytest.approx(200.0 / (100 / 800 + 100 / 900))
