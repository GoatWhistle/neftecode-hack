"""Инструмент get_response_effect отвечает по β на ht.T6 из живой привязки, а не «недоступно»."""
import pytest

from neftecode.application.use_cases.get_live_advice import decision_context
from neftecode.infrastructure.agentic.factory import build_decision_factory
from neftecode.infrastructure.config.scenario import parse_scenario
from neftecode.infrastructure.live.advisor import bind_forecast, bind_measurements
from neftecode.infrastructure.response.data_model import DataResponseEffect

from _agentic_support import raw, session_for

FORECAST = {"model": "last_pak", "value": 6.0, "lower": 4.0, "upper": 9.0, "available": True, "reason": "тест"}
#: Оценка τ = 2026-01-01 (окно 2025) — те же числа, что пишет `train` в artifacts/response_model.json.
RESPONSE = {"schema_version": "v1", "tag": "ht.T6", "flow_tag": "ht.F9", "tau": "2026-01-01", "window_months": 12,
            "beta_mgkg_per_c": -0.4332, "ci": [-0.4761, -0.397], "envelope_dt_c": 2.0, "n_rows": 48925, "method": "тест",
            "drift": [], "flow_beta": None, "model_fingerprint": "x", "t6_range_c": [342.9, 386.1],
            "f9_range_tph": [150.3, 256.7], "weak_strong": [-0.217, -0.739]}


def reading(value):
    return {"value": value, "time": "2026-01-05T08:00:00", "age_min": 0.0, "max_age_min": 30.0}


def bound(t6=367.8):
    measured = {"ht.T6": reading(t6), "ht.F9": reading(206.1), "ht.F26": reading(244.1)}
    document = bind_measurements(raw("baseline"), measured, {"density_kgm3": 836.1}, RESPONSE, FORECAST)
    return bind_forecast(document, FORECAST)


def test_data_effect_is_beta_times_delta_with_its_ranges():
    context = decision_context("2026-01-05T08:00:00", FORECAST, bound())
    effect = DataResponseEffect().effect(context, 1.0)
    assert effect["available"] is True
    assert effect["sulfur_change_mgkg"] == pytest.approx(-0.4332)
    assert effect["sulfur_change_ci_mgkg"] == [pytest.approx(-0.4761), pytest.approx(-0.397)]
    assert effect["sulfur_change_next_half_year_mgkg"] == [pytest.approx(-0.739), pytest.approx(-0.217)]
    assert effect["reference_temp_c"] == pytest.approx(367.8)


def test_data_effect_is_unavailable_without_a_live_binding_outside_the_region_and_beyond_the_envelope():
    effect = DataResponseEffect()
    assert effect.effect({}, 1.0)["available"] is False
    outside = decision_context("2026-01-09T01:10:00", FORECAST, bound(t6=296.8))
    answer = effect.effect(outside, 1.0)
    assert answer["available"] is False and "вне области" in answer["reason"]
    inside = decision_context("2026-01-05T08:00:00", FORECAST, bound())
    assert effect.effect(inside, 2.5)["available"] is False


def test_the_tool_answers_with_data_in_a_live_session():
    document = bound()
    context = decision_context("2026-01-05T08:00:00", FORECAST, document)
    session = session_for("baseline", document=document, live_context=context)
    session.response_effect = DataResponseEffect()
    answer = session.response_effect_for(1.0)
    assert answer["data_model"]["available"] is True
    assert answer["data_model"]["sulfur_change_mgkg"] == pytest.approx(-0.4332)


def test_the_default_factory_wires_the_data_effect():
    factory = build_decision_factory({"AGENTIC_DECISION_ENABLED": "1", "LLM_PROVIDER": "scripted"})
    maker = factory(parse_scenario(raw("baseline")))
    assert isinstance(maker.response_effect, DataResponseEffect)
