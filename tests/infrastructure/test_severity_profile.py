import copy
import json
from pathlib import Path

import pytest

from neftecode.domain.production.economics import Economics
from neftecode.domain.production.severity_profile import build_profile, comparable, delta, evaluate
from neftecode.infrastructure.config.scenario import parse_scenario
from test_measurement_binding import DENSITY, bind_measurements, forecast, measured, response

RAW = json.loads(Path("config/scenarios/baseline.json").read_text(encoding="utf-8"))
MISSING = "нет профиля"


def profile(**kw):
    args = dict(reference_temp_c=348.0, temp_max_c=375.0, reference_flow_m3h=256.0, flow_max_m3h=300.0,
                temp_min_c=330.0, max_severity_index=0.75)
    return build_profile(**{**args, **kw})


def test_components_follow_temperature_and_flow_at_a_fixed_profile():
    p = profile()
    base = evaluate(p, 348.0, 256.0, MISSING)
    hotter = evaluate(p, 361.5, 256.0, MISSING)
    faster = evaluate(p, 348.0, 278.0, MISSING)
    assert base["index"] == 0.0
    assert hotter["terms"]["temperature_above_reference"] == pytest.approx(0.5)
    assert hotter["terms"]["throughput_above_reference"] == 0.0
    assert faster["terms"]["throughput_above_reference"] == pytest.approx(0.5)
    assert hotter["index"] == pytest.approx(0.7 * 0.5)
    assert faster["index"] == pytest.approx(0.3 * 0.5)
    assert evaluate(p, 370.0, 256.0, MISSING)["index"] > hotter["index"]


def test_the_current_mode_compared_with_itself_is_not_zeroed_by_definition():
    p = profile()
    current = evaluate(p, 367.8, 270.0, MISSING)
    assert current["index"] > 0.5
    assert comparable(current, current) and delta(current, current) == 0.0


def test_unknown_inputs_and_bad_scales_are_unavailable_not_zero():
    p = profile()
    assert evaluate(p, None, 256.0, MISSING)["index"] is None
    assert evaluate(p, 350.0, float("nan"), MISSING)["available"] is False
    assert profile(temp_max_c=348.0) is None
    assert profile(flow_max_m3h=100.0) is None
    assert profile(reference_temp_c=None) is None
    assert evaluate(None, 350.0, 260.0, MISSING) == {"available": False, "index": None, "reason": MISSING}


def test_delta_requires_the_same_profile():
    a = evaluate(profile(), 360.0, 260.0, MISSING)
    other = evaluate(profile(temp_max_c=380.0), 360.0, 260.0, MISSING)
    assert not comparable(a, other) and delta(a, other) is None
    assert delta(a, None) is None


def test_limits_are_separate_and_the_model_region_is_not_called_a_safe_limit():
    p = profile(model_region={"t6_range_c": [342.9, 386.1]})
    limits = {l["kind"]: l for l in evaluate(p, 367.8, 256.0, MISSING)["limits"]}
    assert set(limits) == {"passport", "model_region", "scenario"}
    assert limits["passport"]["known"] is False and "headroom" not in limits["passport"]
    assert limits["model_region"]["headroom"] == pytest.approx(386.1 - 367.8)
    assert "не предел безопасной работы" in limits["model_region"]["note"]
    assert limits["scenario"]["headroom"] == pytest.approx(375.0 - 367.8)
    assert limits["scenario"]["index_headroom"] == pytest.approx(0.75 - evaluate(p, 367.8, 256.0, MISSING)["index"])
    bare = {l["kind"]: l for l in evaluate(profile(), 350.0, 256.0, MISSING)["limits"]}
    assert bare["model_region"]["known"] is False


def test_live_binding_keeps_the_severity_scale_fixed_while_the_response_reference_moves():
    bound = bind_measurements(copy.deepcopy(RAW), measured(t6=367.8, f9=206.1), DENSITY, response(), forecast())
    model = bound["stages"]["hydrotreating"]["model"]
    fixed = bound["policy"]["severity_profile"]
    assert model["reference_temp_c"] == pytest.approx(367.8)
    assert fixed["reference_temp_c"] == 348.0 and fixed["temp_scale_c"] == pytest.approx(27.0)
    assert fixed["source"] == "scenario_proxy"
    assert fixed["model_region"]["t6_range_c"] == [342.9, 386.1]
    econ = Economics(parse_scenario(bound))
    now = econ.severity({"ht_reactor_inlet_temp_c": 367.8, "ht_feed_flow_m3h": 250.0})
    assert now["index"] == pytest.approx(0.7 * (367.8 - 348.0) / 27.0)
    assert now["profile_version"] == fixed["version"]


def test_the_profile_does_not_change_the_response_model_or_the_scale_with_the_mode():
    with_profile = bind_measurements(copy.deepcopy(RAW), measured(t6=367.8), DENSITY, response(), forecast())
    preset = copy.deepcopy(RAW)
    preset["policy"]["severity_profile"] = {"sentinel": True}
    without = bind_measurements(preset, measured(t6=367.8), DENSITY, response(), forecast())
    assert with_profile["stages"] == without["stages"]
    assert with_profile["tanks"] == without["tanks"]
    other_mode = bind_measurements(copy.deepcopy(RAW), measured(t6=355.0), DENSITY, response(), forecast())
    assert other_mode["policy"]["severity_profile"]["reference_temp_c"] == \
        with_profile["policy"]["severity_profile"]["reference_temp_c"]
    assert other_mode["policy"]["severity_profile"]["temp_scale_c"] == \
        with_profile["policy"]["severity_profile"]["temp_scale_c"]


def test_profiles_with_different_weights_have_different_ids_and_no_delta():
    temp_only = profile(weights={"temperature_above_reference": 1.0, "throughput_above_reference": 0.0})
    flow_only = profile(weights={"temperature_above_reference": 0.0, "throughput_above_reference": 1.0})
    a = evaluate(temp_only, 360.0, 256.0, MISSING)
    b = evaluate(flow_only, 360.0, 256.0, MISSING)
    assert a["profile_id"] != b["profile_id"]
    assert not comparable(a, b)
    assert delta(a, b) is None


def test_profiles_with_equal_parameters_stay_comparable():
    a = evaluate(profile(), 360.0, 256.0, MISSING)
    b = evaluate(profile(), 370.0, 280.0, MISSING)
    assert a["profile_id"] == b["profile_id"]
    assert comparable(a, b)

