"""Hydrotreating response: delayed, non-retroactive, and never double counted."""
import json
from pathlib import Path

import pytest

from neftecode.domain.production.process import (IN_REGION, OUT_OF_REGION, ChainModel, HydrotreatingModel,
                               ProcessError, StreamState)
from neftecode.infrastructure.config.scenario import load_scenario, parse_scenario

BASELINE = Path("config/scenarios/baseline.json")
SOUR = Path("config/scenarios/sour_crude.json")


def chain(path=BASELINE):
    return ChainModel(load_scenario(path))


def model():
    return chain().hydrotreating


def feed(sulfur=1012.5, flow=222.0, t95=355.0, applicability=IN_REGION):
    return StreamState(flow, sulfur, t95, 865.0, applicability)


# --- Coefficients come from the scenario ---

def test_coefficients_come_from_the_scenario():
    raw = json.loads(BASELINE.read_text())["stages"]["hydrotreating"]["model"]
    assert model().reference_temp_c == raw["reference_temp_c"]
    assert model().severity_exponent == raw["severity_exponent"]
    assert model().response_lag_hours == 2.0


def test_missing_coefficients_are_refused_by_name():
    raw = json.loads(BASELINE.read_text())
    del raw["stages"]["hydrotreating"]["model"]["severity_exponent"]
    with pytest.raises(ProcessError, match="severity_exponent"):
        ChainModel(parse_scenario(raw))


def test_impossible_conversion_share_is_refused():
    raw = json.loads(BASELINE.read_text())
    raw["stages"]["hydrotreating"]["model"]["conversion_at_reference"] = 1.0
    with pytest.raises(ProcessError, match="строго между 0 и 1"):
        ChainModel(parse_scenario(raw))


def test_model_states_it_is_an_action_model_not_a_forecast():
    assert "не прогноз по истории" in model().to_dict()["note"]
    assert "Прогноз по истории" in chain().to_dict()["note"]


# --- Declared directions ---

def test_hotter_reactor_removes_more_sulfur():
    base = model().run(feed(), {"ht_reactor_inlet_temp_c": 348.0, "ht_feed_flow_m3h": 256.0})
    hot = model().run(feed(), {"ht_reactor_inlet_temp_c": 356.0, "ht_feed_flow_m3h": 256.0})
    assert hot.sulfur_mgkg < base.sulfur_mgkg


def test_higher_throughput_removes_less_sulfur():
    base = model().run(feed(), {"ht_reactor_inlet_temp_c": 348.0, "ht_feed_flow_m3h": 256.0})
    fast = model().run(feed(), {"ht_reactor_inlet_temp_c": 348.0, "ht_feed_flow_m3h": 290.0})
    assert fast.sulfur_mgkg > base.sulfur_mgkg


def test_outlet_sulfur_never_exceeds_inlet_sulfur():
    for temp in (330.0, 348.0, 375.0):
        for flow in (180.0, 256.0, 300.0):
            result = model().run(feed(), {"ht_reactor_inlet_temp_c": temp, "ht_feed_flow_m3h": flow})
            assert 0 <= result.sulfur_mgkg <= 1012.5


def test_worse_crude_reaches_the_product_through_the_chain():
    assert chain(SOUR).run_at(0.0).sulfur_mgkg > chain().run_at(0.0).sulfur_mgkg


def test_mass_flow_passes_through_the_reactor_unchanged():
    cut = feed()
    assert model().run(cut, {"ht_reactor_inlet_temp_c": 348.0,
                             "ht_feed_flow_m3h": 256.0}).flow_tph == cut.flow_tph


# --- Delay: an action cannot act before its lag has elapsed ---

def test_no_action_leaves_the_product_unchanged_over_the_whole_horizon():
    c = chain()
    values = [c.run_at(t).sulfur_mgkg for t in (0.0, 0.5, 1.0, 2.0, 3.0)]
    assert len(set(round(v, 9) for v in values)) == 1


def test_a_correction_has_no_effect_before_its_lag_elapses():
    c = chain()
    pending = ((0.0, {"ht_reactor_inlet_temp_c": 354.0}),)
    before = c.run_at(1.9, pending).sulfur_mgkg
    assert before == pytest.approx(c.run_at(1.9).sulfur_mgkg), "эффект появился раньше запаздывания"


def test_the_correction_takes_effect_exactly_at_the_declared_lag():
    c = chain()
    pending = ((0.0, {"ht_reactor_inlet_temp_c": 354.0}),)
    assert c.run_at(2.0, pending).sulfur_mgkg < c.run_at(1.9, pending).sulfur_mgkg


def test_an_action_never_changes_the_past():
    c = chain()
    baseline = c.run_at(0.0).sulfur_mgkg
    pending = ((1.0, {"ht_reactor_inlet_temp_c": 360.0}),)
    assert c.run_at(0.0, pending).sulfur_mgkg == pytest.approx(baseline)


def test_a_move_made_later_acts_later():
    c = chain()
    early = ((0.0, {"ht_reactor_inlet_temp_c": 354.0}),)
    late = ((1.0, {"ht_reactor_inlet_temp_c": 354.0}),)
    assert c.run_at(2.5, early).sulfur_mgkg < c.run_at(2.5, late).sulfur_mgkg


# --- Successive changes supersede, they do not accumulate ---

def test_two_successive_moves_do_not_add_their_effects():
    """The second setpoint replaces the first; adding both would count one change twice."""
    m = model()
    acting = m.effective_controls(3.0, {"ht_reactor_inlet_temp_c": 348.0, "ht_feed_flow_m3h": 256.0},
                                  ((0.0, {"ht_reactor_inlet_temp_c": 352.0}),
                                   (0.5, {"ht_reactor_inlet_temp_c": 356.0})))
    assert acting["ht_reactor_inlet_temp_c"] == 356.0, "уставка заменяется, а не складывается"


def test_the_latest_move_already_in_effect_wins():
    m = model()
    acting = m.effective_controls(2.4, {"ht_reactor_inlet_temp_c": 348.0, "ht_feed_flow_m3h": 256.0},
                                  ((0.0, {"ht_reactor_inlet_temp_c": 352.0}),
                                   (1.0, {"ht_reactor_inlet_temp_c": 356.0})))
    assert acting["ht_reactor_inlet_temp_c"] == 352.0, "вторая коррекция ещё не подействовала"


def test_repeating_the_same_recommendation_changes_nothing():
    c = chain()
    once = c.run_at(3.0, ((0.0, {"ht_reactor_inlet_temp_c": 354.0}),)).sulfur_mgkg
    twice = c.run_at(3.0, ((0.0, {"ht_reactor_inlet_temp_c": 354.0}),
                           (0.5, {"ht_reactor_inlet_temp_c": 354.0}))).sulfur_mgkg
    assert once == pytest.approx(twice)


def test_moves_are_ordered_by_time_not_by_listing_order():
    m = model()
    current = {"ht_reactor_inlet_temp_c": 348.0, "ht_feed_flow_m3h": 256.0}
    unordered = ((0.5, {"ht_reactor_inlet_temp_c": 356.0}), (0.0, {"ht_reactor_inlet_temp_c": 352.0}))
    assert m.effective_controls(3.0, current, unordered)["ht_reactor_inlet_temp_c"] == 356.0


@pytest.mark.parametrize("time_hours", [-1.0, float("nan")])
def test_negative_or_unknown_time_is_refused(time_hours):
    with pytest.raises(ProcessError, match="конечным и неотрицательным"):
        model().effective_controls(time_hours, {"ht_reactor_inlet_temp_c": 348.0})


# --- Outside the declared region ---

def test_temperature_outside_the_range_is_marked_out_of_region():
    result = model().run(feed(), {"ht_reactor_inlet_temp_c": 400.0, "ht_feed_flow_m3h": 256.0})
    assert result.applicability == OUT_OF_REGION
    assert result.usable is False


def test_an_out_of_region_feed_contaminates_the_result():
    result = model().run(feed(applicability=OUT_OF_REGION),
                         {"ht_reactor_inlet_temp_c": 348.0, "ht_feed_flow_m3h": 256.0})
    assert result.applicability == OUT_OF_REGION
    assert any("вне области модели АВТ" in note for note in result.notes)


def test_unknown_feed_sulfur_gives_unknown_output_not_zero():
    result = model().run(feed(sulfur=None), {"ht_reactor_inlet_temp_c": 348.0, "ht_feed_flow_m3h": 256.0})
    assert result.sulfur_mgkg is None
    assert result.applicability == OUT_OF_REGION


def test_zero_throughput_is_refused_rather_than_dividing_by_zero():
    with pytest.raises(ProcessError, match="положительным"):
        model().run(feed(), {"ht_reactor_inlet_temp_c": 348.0, "ht_feed_flow_m3h": 0.0})


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_non_finite_setpoint_is_refused(value):
    with pytest.raises(ProcessError, match="конечным"):
        model().run(feed(), {"ht_reactor_inlet_temp_c": value, "ht_feed_flow_m3h": 256.0})


def test_every_result_says_the_response_is_not_measured():
    result = model().run(feed(), {"ht_reactor_inlet_temp_c": 348.0, "ht_feed_flow_m3h": 256.0})
    assert any("не является" in note for note in result.notes)
    assert any("запаздывание" in note for note in result.notes)


# --- The chain as a whole ---

def test_the_chain_is_reproducible():
    assert chain().run_at(1.5).to_dict() == chain().run_at(1.5).to_dict()


def test_an_avt_move_also_respects_its_own_lag():
    c = chain()
    pending = ((0.0, {"avt_furnace_outlet_temp_c": 380.0}),)
    assert c.run_at(0.4, pending).sulfur_mgkg == pytest.approx(c.run_at(0.4).sulfur_mgkg)
    assert c.run_at(0.6, pending).sulfur_mgkg != pytest.approx(c.run_at(0.6).sulfur_mgkg)


def test_current_controls_cover_both_stages():
    controls = chain().current_controls()
    assert {"crude_feed_rate_tph", "avt_furnace_outlet_temp_c",
            "ht_reactor_inlet_temp_c", "ht_feed_flow_m3h"} <= set(controls)
