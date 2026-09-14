"""A broken scenario must fail loudly at load, not quietly produce a permissive plan."""
import copy
import json
from pathlib import Path

import pytest

from neftecode.infrastructure.config.scenario import (QUALITIES, Scenario, ScenarioError, describe, load_scenario,
                                parse_scenario)

SCENARIOS = Path("config/scenarios")


def raw(name="baseline"):
    return json.loads((SCENARIOS / f"{name}.json").read_text())


def test_all_shipped_scenarios_load():
    for path in sorted(SCENARIOS.glob("*.json")):
        scenario = load_scenario(path)
        assert isinstance(scenario, Scenario)
        assert scenario.kind == "synthetic_blending_scenario"
        assert scenario.assumptions, f"{path}: сценарий без явных допущений"


def test_scenarios_cover_normal_problem_and_no_solution():
    outcomes = {load_scenario(p).expected.get("outcome") for p in SCENARIOS.glob("*.json")}
    assert "hold" in outcomes, "нет сценария нормального режима"
    assert "refuse" in outcomes, "нет сценария, где допустимого решения не существует"
    assert len(outcomes) >= 3, "нет отдельного проблемного набора условий"


def test_horizon_matches_case_and_step_divides_it():
    scenario = load_scenario(SCENARIOS / "baseline.json")
    assert 0 < scenario.horizon.hours <= 3
    assert scenario.horizon.steps * scenario.horizon.step_minutes == scenario.horizon.hours * 60
    assert scenario.horizon.times_hours()[-1] == scenario.horizon.hours


@pytest.mark.parametrize("hours", [0, -1, 4, 24])
def test_horizon_outside_case_range_is_rejected(hours):
    data = raw()
    data["horizon"]["hours"] = hours
    with pytest.raises(ScenarioError, match="горизонт"):
        parse_scenario(data)


def test_step_not_dividing_horizon_is_rejected():
    data = raw()
    data["horizon"]["step_minutes"] = 40
    with pytest.raises(ScenarioError, match="не делит горизонт"):
        parse_scenario(data)


def test_wrong_unit_is_rejected_instead_of_converted():
    data = raw()
    data["tanks"][0]["inventory"]["unit"] = "кг"
    with pytest.raises(ScenarioError, match="не совпадает с ожидаемой"):
        parse_scenario(data)


def test_quantity_without_source_is_rejected():
    data = raw()
    del data["tanks"][0]["cost_per_t"]["source"]
    with pytest.raises(ScenarioError, match="source"):
        parse_scenario(data)


def test_unknown_provenance_is_rejected():
    data = raw()
    data["tanks"][0]["cost_per_t"]["source"] = "измерено"
    with pytest.raises(ScenarioError, match="не из набора"):
        parse_scenario(data)


def test_bare_number_cannot_impersonate_a_measured_quantity():
    data = raw()
    data["tanks"][0]["inventory"] = 4000.0
    with pytest.raises(ScenarioError, match="ожидается объект"):
        parse_scenario(data)


def test_scenario_cannot_relax_the_hard_sulfur_limit():
    data = raw()
    data["product"]["sulfur_mgkg"]["value"] = 15.0
    with pytest.raises(ScenarioError, match="мягче"):
        parse_scenario(data)


def test_missing_sulfur_limit_is_rejected():
    data = raw()
    data["product"]["sulfur_mgkg"] = None
    with pytest.raises(ScenarioError, match="жёсткое требование"):
        parse_scenario(data)


def test_unset_t95_limit_stays_unknown_rather_than_absent():
    data = raw()
    data["product"]["t95_c"] = None
    scenario = parse_scenario(data)
    assert scenario.product.limit_value("t95_c") is None
    assert "t95_c" in scenario.product.unknown_limits()
    assert scenario.product.limit_value("sulfur_mgkg") == 10.0


def test_unknown_tank_property_is_preserved_not_defaulted():
    scenario = load_scenario(SCENARIOS / "baseline.json")
    light = scenario.tank("light")
    assert light.property_value("cetane_number") is None
    assert light.property_value("sulfur_mgkg") == 6.0
    assert "cetane_number" in scenario.unknown_properties()["light"]


def test_tank_without_sulfur_is_rejected():
    data = raw()
    data["tanks"][0]["properties"]["sulfur_mgkg"] = None
    with pytest.raises(ScenarioError, match="сера компонента обязательна"):
        parse_scenario(data)


def test_single_tank_is_rejected():
    data = raw()
    data["tanks"] = data["tanks"][:1]
    with pytest.raises(ScenarioError, match="не менее двух резервуаров"):
        parse_scenario(data)


def test_identical_tanks_are_rejected():
    data = raw()
    for tank in data["tanks"][1:]:
        tank["properties"]["sulfur_mgkg"]["value"] = data["tanks"][0]["properties"]["sulfur_mgkg"]["value"]
    with pytest.raises(ScenarioError, match="одинаковую серу"):
        parse_scenario(data)


def test_all_tanks_unavailable_is_rejected():
    data = raw()
    for tank in data["tanks"]:
        tank["available"] = False
    with pytest.raises(ScenarioError, match="ни один резервуар не доступен"):
        parse_scenario(data)


def test_unavailable_tank_is_excluded_from_available_set():
    scenario = load_scenario(SCENARIOS / "no_feasible.json")
    assert "reserve" not in [t.tank_id for t in scenario.available_tanks()]
    assert "reserve" in [t.tank_id for t in scenario.tanks]


def test_control_outside_its_own_range_is_rejected():
    data = raw()
    data["stages"]["avt"]["controls"]["crude_feed_rate_tph"]["current"]["value"] = 900.0
    with pytest.raises(ScenarioError, match="вне"):
        parse_scenario(data)


def test_control_absent_from_the_parameter_map_is_rejected():
    data = raw()
    data["stages"]["avt"]["controls"]["ht_P8_raw"] = {
        "min": {"value": 0, "unit": "°C", "source": "scenario"},
        "max": {"value": 1, "unit": "°C", "source": "scenario"},
        "current": {"value": 0.5, "unit": "°C", "source": "scenario"}}
    with pytest.raises(ScenarioError, match="карте управляющих"):
        parse_scenario(data)


@pytest.mark.parametrize("lag", [-0.5, 3.5, 12])
def test_response_lag_outside_case_range_is_rejected(lag):
    data = raw()
    data["stages"]["hydrotreating"]["response_lag_hours"]["value"] = lag
    with pytest.raises(ScenarioError, match="запаздывание|отрицательное"):
        parse_scenario(data)


def test_missing_stage_is_rejected():
    data = raw()
    del data["stages"]["hydrotreating"]
    with pytest.raises(ScenarioError, match="hydrotreating"):
        parse_scenario(data)


def test_additive_cannot_be_credited_with_removing_sulfur():
    data = raw()
    data["additive"]["affects"] = ["cetane_number", "sulfur_mgkg"]
    with pytest.raises(ScenarioError, match="удаление серы"):
        parse_scenario(data)


def test_additive_dose_above_expert_limit_is_rejected():
    data = raw()
    data["additive"]["max_dose_fraction"]["value"] = 0.05
    with pytest.raises(ScenarioError, match="3%"):
        parse_scenario(data)


def test_scenario_must_declare_itself_synthetic():
    data = raw()
    data["kind"] = "plant_data"
    with pytest.raises(ScenarioError, match="synthetic_blending_scenario"):
        parse_scenario(data)


def test_wrong_schema_is_rejected():
    data = raw()
    data["schema"] = "neftecode.domain.production.scenario.v0"
    with pytest.raises(ScenarioError, match="схема"):
        parse_scenario(data)


def test_scenario_without_assumptions_is_rejected():
    data = raw()
    data["assumptions"] = []
    with pytest.raises(ScenarioError, match="допущения"):
        parse_scenario(data)


def test_negative_inventory_is_rejected():
    data = raw()
    data["tanks"][0]["inventory"]["value"] = -1.0
    with pytest.raises(ScenarioError, match="отрицательное"):
        parse_scenario(data)


def test_missing_file_and_broken_json_are_reported_clearly(tmp_path):
    with pytest.raises(ScenarioError, match="не найден"):
        load_scenario(tmp_path / "absent.json")
    broken = tmp_path / "broken.json"
    broken.write_text("{not json")
    with pytest.raises(ScenarioError, match="некорректный JSON"):
        load_scenario(broken)


def test_scenario_quantities_are_never_reported_as_measured():
    scenario = load_scenario(SCENARIOS / "baseline.json")
    for tank in scenario.tanks:
        assert not tank.inventory.measured, f"{tank.tank_id}: остаток выдан за измерение"
        assert not tank.cost_per_t.measured
    assert scenario.product.limits["sulfur_mgkg"].measured, "предел ТЗ должен иметь статус given"
    assert not scenario.product.limits["t95_c"].measured, "предел T95 не задан ТЗ и не может быть given"


def test_describe_reports_gaps_rather_than_hiding_them():
    summary = describe(load_scenario(SCENARIOS / "baseline.json"))
    assert summary["tanks_with_unknown_properties"] == {"light": ["cetane_number"]}
    assert summary["available_tanks"] == ["main", "reserve", "light"]
    assert summary["total_inventory_t"] == 4000.0 + 600.0 + 900.0
    assert set(QUALITIES) >= set(summary["unknown_product_limits"])
    assert summary["assumptions"]


def test_expected_outcome_is_recorded_before_tuning():
    """Rules of evaluation are fixed in the scenario file, not chosen after seeing results."""
    for path in SCENARIOS.glob("*.json"):
        scenario = load_scenario(path)
        assert scenario.expected.get("outcome"), f"{path}: не зафиксирован ожидаемый исход"


def test_round_trip_preserves_units_and_provenance():
    scenario = load_scenario(SCENARIOS / "baseline.json")
    restored = parse_scenario(json.loads(json.dumps(scenario.to_dict(), ensure_ascii=False)))
    assert restored.to_dict() == scenario.to_dict()
    assert copy.deepcopy(scenario).tanks[0].inventory.source == "scenario"


# --- Every control says how a change is executed (Q&A 11.09: plants run feedback control) ---

def test_every_shipped_control_is_a_setpoint_for_a_feedback_loop():
    for path in sorted(SCENARIOS.glob("*.json")):
        for stage in load_scenario(path).stages.values():
            for name, spec in stage.controls.items():
                actuation = spec["actuation"]
                assert actuation.kind == "feedback_setpoint", f"{path}: {name}"
                assert actuation.loop.strip() and actuation.source == "given"


def test_control_without_actuation_is_rejected():
    data = raw()
    del data["stages"]["avt"]["controls"]["crude_feed_rate_tph"]["actuation"]
    with pytest.raises(ScenarioError, match="actuation"):
        parse_scenario(data)


def test_unknown_actuation_kind_is_rejected():
    data = raw()
    data["stages"]["hydrotreating"]["controls"]["ht_reactor_inlet_temp_c"]["actuation"]["kind"] = "valve_open"
    with pytest.raises(ScenarioError, match="способ исполнения"):
        parse_scenario(data)


def test_actuation_without_a_loop_description_is_rejected():
    data = raw()
    data["stages"]["avt"]["controls"]["avt_furnace_outlet_temp_c"]["actuation"]["loop"] = " "
    with pytest.raises(ScenarioError, match="контур"):
        parse_scenario(data)


def test_actuation_survives_serialisation():
    stage = parse_scenario(raw()).stages["hydrotreating"].to_dict()
    assert stage["controls"]["ht_reactor_inlet_temp_c"]["actuation"]["measured_tag"] == "ht.P8"
