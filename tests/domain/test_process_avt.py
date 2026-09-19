import copy
import json
from pathlib import Path

import pytest

from neftecode.domain.production.process import IN_REGION, OUT_OF_REGION, AvtModel, AvtStage, ProcessError
from neftecode.infrastructure.config.scenario import parse_scenario

BASELINE = Path("config/scenarios/baseline.json")


def scenario(**overrides):
    raw = json.loads(BASELINE.read_text(encoding="utf-8"))
    for path, value in overrides.items():
        node = raw
        parts = path.split(".")
        for key in parts[:-1]:
            node = node[key]
        node[parts[-1]] = value
    return parse_scenario(raw)


def stage(**overrides):
    return AvtStage(scenario(**overrides))



def test_model_coefficients_come_from_the_scenario():
    model = stage().model
    raw = json.loads(BASELINE.read_text(encoding="utf-8"))["stages"]["avt"]["model"]
    assert model.reference_temp_c == raw["reference_temp_c"]
    assert model.sulfur_partition == raw["sulfur_partition"]
    assert model.temp_range_c == (350.0, 400.0)


def test_missing_coefficients_are_refused_by_name():
    raw = json.loads(BASELINE.read_text(encoding="utf-8"))
    del raw["stages"]["avt"]["model"]["sulfur_partition"]
    with pytest.raises(ProcessError, match="sulfur_partition"):
        AvtStage(parse_scenario(raw))


def test_model_declares_itself_as_a_scenario_response():
    described = stage().model.to_dict()
    assert described["provenance"] == "scenario"
    assert "не подтверждены данными завода" in described["note"]


def test_every_result_carries_the_scenario_note():
    result = stage().run()
    assert any("сценарная модель" in note for note in result.notes)



def test_diesel_flow_matches_hand_computation_at_the_reference_point():
    result = stage().run()
    assert result.flow_tph == pytest.approx(740.0 * 0.30)


def test_diesel_sulfur_matches_hand_computation_at_the_reference_point():
    result = stage().run()
    assert result.sulfur_mgkg == pytest.approx(1.35 * 10_000 * 0.075)


def test_t95_equals_its_reference_value_at_the_reference_temperature():
    assert stage().run().t95_c == pytest.approx(355.0)


def test_conversion_from_mass_percent_to_mg_per_kg_is_ten_thousand():
    doubled = stage(**{"crude.sulfur_wt_pct": {"value": 2.70, "unit": "% масс.", "source": "scenario"}})
    assert doubled.run().sulfur_mgkg == pytest.approx(2 * stage().run().sulfur_mgkg)



def test_hotter_furnace_gives_a_heavier_cut_on_all_three_outputs():
    base = stage().run()
    hot = stage().run({"avt_furnace_outlet_temp_c": 380.0})
    assert hot.flow_tph > base.flow_tph
    assert hot.sulfur_mgkg > base.sulfur_mgkg
    assert hot.t95_c > base.t95_c


def test_cooler_furnace_moves_every_output_the_other_way():
    base = stage().run()
    cool = stage().run({"avt_furnace_outlet_temp_c": 364.0})
    assert cool.flow_tph < base.flow_tph
    assert cool.sulfur_mgkg < base.sulfur_mgkg
    assert cool.t95_c < base.t95_c


def test_worse_crude_raises_diesel_sulfur_without_touching_the_flow():
    base = stage().run()
    sour = AvtStage(parse_scenario(json.loads(Path("config/scenarios/sour_crude.json").read_text(encoding="utf-8")))).run()
    assert sour.sulfur_mgkg > base.sulfur_mgkg
    assert sour.flow_tph == pytest.approx(base.flow_tph), "состав сырья не меняет выход в этой модели"


def test_more_feed_scales_the_cut_proportionally():
    base = stage().run()
    more = stage().run({"crude_feed_rate_tph": 800.0})
    assert more.flow_tph == pytest.approx(base.flow_tph * 800.0 / 740.0)
    assert more.sulfur_mgkg == pytest.approx(base.sulfur_mgkg), "расход сырья не меняет долю серы"



def test_the_cut_never_exceeds_the_feed():
    for temp in (350.0, 372.0, 400.0):
        result = stage().run({"avt_furnace_outlet_temp_c": temp})
        assert 0 <= result.flow_tph <= 740.0


def test_diesel_sulfur_stays_below_the_crude_sulfur():
    crude_mgkg = 1.35 * 10_000
    for temp in (350.0, 372.0, 400.0):
        assert stage().run({"avt_furnace_outlet_temp_c": temp}).sulfur_mgkg < crude_mgkg



def test_temperature_above_the_declared_range_is_marked_out_of_region():
    result = stage().run({"avt_furnace_outlet_temp_c": 420.0})
    assert result.applicability == OUT_OF_REGION
    assert any("вне области модели" in note for note in result.notes)
    assert result.usable is False


def test_feed_below_the_declared_range_is_marked_out_of_region():
    result = stage().run({"crude_feed_rate_tph": 100.0})
    assert result.applicability == OUT_OF_REGION


def test_inside_the_declared_range_the_result_is_usable():
    result = stage().run({"avt_furnace_outlet_temp_c": 360.0})
    assert result.applicability == IN_REGION
    assert result.usable is True


def test_negative_model_sulfur_becomes_unknown_rather_than_a_number():
    raw = json.loads(BASELINE.read_text(encoding="utf-8"))
    raw["stages"]["avt"]["model"]["sulfur_per_degree"] = -1.0
    result = AvtStage(parse_scenario(raw)).run({"avt_furnace_outlet_temp_c": 375.0})
    assert result.sulfur_mgkg is None
    assert result.applicability == OUT_OF_REGION
    assert result.usable is False


def test_non_positive_yield_reports_out_of_region_instead_of_a_negative_flow():
    raw = json.loads(BASELINE.read_text(encoding="utf-8"))
    raw["stages"]["avt"]["model"]["yield_per_degree"] = -1.0
    result = AvtStage(parse_scenario(raw)).run({"avt_furnace_outlet_temp_c": 375.0})
    assert result.flow_tph == 0.0
    assert result.applicability == OUT_OF_REGION


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_non_finite_control_is_refused(value):
    with pytest.raises(ProcessError, match="конечным"):
        stage().run({"avt_furnace_outlet_temp_c": value})


def test_negative_flow_cannot_be_constructed():
    from neftecode.domain.production.process import StreamState
    with pytest.raises(ProcessError, match="неотрицательным"):
        StreamState(-1.0, 8.0)



def test_the_stage_needs_no_history_only_the_scenario_and_the_setpoints():
    result = stage().run({"avt_furnace_outlet_temp_c": 370.0})
    assert result.sulfur_mgkg is not None


def test_two_identical_calls_give_identical_results():
    assert stage().run({"avt_furnace_outlet_temp_c": 366.0}).to_dict() == \
           stage().run({"avt_furnace_outlet_temp_c": 366.0}).to_dict()


def test_current_controls_come_from_the_scenario():
    assert stage().current_controls() == {"crude_feed_rate_tph": 740.0,
                                          "avt_furnace_outlet_temp_c": 372.0}


def test_model_can_be_built_directly_from_a_stage():
    model = AvtModel.from_stage(scenario().stages["avt"])
    assert isinstance(model, AvtModel)
    assert model.feed_range_tph == (600.0, 820.0)


def test_deep_copy_of_a_scenario_yields_the_same_response():
    original = scenario()
    assert AvtStage(copy.deepcopy(original)).run().to_dict() == AvtStage(original).run().to_dict()
