import json
from pathlib import Path

import pytest

from neftecode.application.services.chain_blocks import (DATA_BETA, MASS_BALANCE, SCENARIO_KINETICS,
                                                         SCENARIO_MODEL, chain_view)
from neftecode.application.services.explain import explain
from neftecode.application.use_cases.make_decision import MakeDecision
from neftecode.domain.advisory.optimizer import DEFAULT_BUDGET
from neftecode.infrastructure.config.scenario import load_scenario, parse_scenario
from neftecode.infrastructure.live.advisor import bind_forecast, bind_measurements

SCENARIOS = Path("config/scenarios")
FORECAST = {"model": "last_pak", "value": 6.0, "lower": 4.0, "upper": 9.0, "available": True, "reason": "тест"}
RESPONSE = {"schema_version": "v1", "tag": "ht.T6", "flow_tag": "ht.F9", "tau": "2026-01-01", "window_months": 12,
            "beta_mgkg_per_c": -0.4226, "ci": [-0.4761, -0.397], "envelope_dt_c": 2.0, "n_rows": 48925,
            "method": "тест", "drift": [], "flow_beta": None, "model_fingerprint": "x",
            "t6_range_c": [342.9, 386.1], "f9_range_tph": [150.3, 256.7], "weak_strong": [-0.217, -0.739]}


def raw(name="baseline"):
    return json.loads((SCENARIOS / f"{name}.json").read_text(encoding="utf-8"))


def reading(value):
    return {"value": value, "time": "2026-01-05T08:00:00", "age_min": 0.0, "max_age_min": 30.0}


def live(t6=367.8):
    # Срез 05.01.2026 08:00: T6, F9, F26 — измерения среза «норма».
    measured = {"ht.T6": reading(t6), "ht.F9": reading(206.1), "ht.F26": reading(244.1)}
    document = bind_measurements(raw(), measured, {"density_kgm3": 836.1}, RESPONSE, FORECAST)
    return bind_forecast(document, FORECAST)


def blocks(view):
    return {block["id"]: block for block in view["blocks"]}


def test_every_chain_block_declares_controllability_and_model_basis():
    for document in (raw(), live()):
        view = chain_view(parse_scenario(document))
        assert [block["id"] for block in view["blocks"]] == ["avt", "hydrotreating", "blending"]
        for block in view["blocks"]:
            assert isinstance(block["controllable"], bool)
            assert block["model_basis"] and block["model_basis_note"] and block["controllable_reason"]


def test_live_slice_0501_avt_is_not_controllable_and_ht_rests_on_beta():
    view = chain_view(parse_scenario(live()))
    assert view["mode"] == "live"
    chain = blocks(view)
    assert chain["avt"]["controllable"] is False
    assert chain["avt"]["model_basis"] == SCENARIO_MODEL
    assert set(chain["avt"]["controls"].values()) == {False}
    assert "промежуточные ёмкости" in chain["avt"]["controllable_reason"]
    assert chain["hydrotreating"]["controllable"] is True
    assert chain["hydrotreating"]["controls"] == {"ht_feed_flow_m3h": False, "ht_reactor_inlet_temp_c": True}
    assert chain["hydrotreating"]["model_basis"] == DATA_BETA
    assert chain["hydrotreating"]["beta_mgkg_per_c"] == pytest.approx(-0.4226)
    assert chain["blending"]["controllable"] is True
    assert chain["blending"]["model_basis"] == MASS_BALANCE


def test_live_outside_the_response_region_leaves_ht_on_scenario_kinetics_without_moves():
    chain = blocks(chain_view(parse_scenario(live(t6=296.8))))
    assert chain["avt"]["controllable"] is False
    assert chain["hydrotreating"]["controllable"] is False
    assert chain["hydrotreating"]["model_basis"] == SCENARIO_KINETICS
    assert "beta_mgkg_per_c" not in chain["hydrotreating"]


def test_scenario_mode_moves_every_block_on_scenario_models():
    view = chain_view(load_scenario(SCENARIOS / "baseline.json"))
    assert view["mode"] == "scenario"
    chain = blocks(view)
    assert all(block["controllable"] for block in chain.values())
    assert chain["avt"]["model_basis"] == SCENARIO_MODEL
    assert chain["hydrotreating"]["model_basis"] == SCENARIO_KINETICS
    assert chain["blending"]["model_basis"] == MASS_BALANCE


def test_live_explanation_carries_the_chain_and_attributes_no_data_effect_to_avt():
    document = live()
    scenario = parse_scenario(document)
    decision = MakeDecision(scenario).decide(budget=DEFAULT_BUDGET)
    explanation = explain(decision, scenario)
    assert explanation["chain"] == chain_view(scenario)
    avt = [s for s in explanation["statements"]
           if s["topic"] in ("control.avt_furnace_outlet_temp_c", "control.crude_feed_rate_tph")]
    assert len(avt) == 2
    for statement in avt:
        assert "не рассматривался" in statement["text"]
        assert "β" not in statement["text"] and "по данным" not in statement["text"]
        assert {e["kind"] for e in statement["evidence"]} <= {"scenario", "policy"}
        assert any(e["ref"] == "policy.disabled_control_moves" for e in statement["evidence"])


def test_refusal_explanation_carries_the_chain_too():
    scenario = load_scenario(SCENARIOS / "no_feasible.json")
    decision = MakeDecision(scenario).decide(budget=DEFAULT_BUDGET)
    assert decision["status"] == "refuse"
    assert explain(decision, scenario)["chain"] == chain_view(scenario)
