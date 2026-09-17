"""Агенты видят живую привязку момента: измерения, уставки, отклик, приток, предупреждения."""
import json

import pytest

from neftecode.application.agentic.context import build_context
from neftecode.application.use_cases.get_live_advice import decision_context
from neftecode.infrastructure.live.advisor import bind_forecast, bind_measurements, load_response_model

from _agentic_support import raw, session_for

FORECAST = {"model": "last_pak", "value": 6.0, "lower": 4.0, "upper": 9.0, "available": True, "reason": "тест"}


def reading(value):
    return {"value": value, "time": "2026-01-05T08:00:00", "age_min": 0.0, "max_age_min": 30.0}


def bound(t6=367.8):
    measured = {"ht.T6": reading(t6), "ht.F9": reading(206.1), "ht.F26": reading(244.1)}
    document = bind_measurements(raw("baseline"), measured, {"density_kgm3": 836.1}, load_response_model("."), FORECAST)
    return bind_forecast(document, FORECAST)


def test_agent_context_carries_measurements_of_the_moment():
    document = bound()
    context = decision_context("2026-01-05T08:00:00", FORECAST, document)
    session = session_for("baseline", document=document, live_context=context)
    text, refs = build_context(session, "quality")
    sections = json.loads(text.split("\n", 1)[1])
    assert "context:measurements" in refs
    assert sections["measurements"]["live"] is True
    assert sections["measurements"]["tags"]["ht.T6"]["value"] == pytest.approx(367.8)
    assert sections["measurements"]["response_model"]["provenance"] == "derived"
    assert sections["measurements"]["tank_inflow"]["source"] == "derived"


def test_out_of_region_warning_reaches_the_agents():
    document = bound(t6=296.8)
    session = session_for("baseline", document=document,
                          live_context=decision_context("2026-01-09T01:10:00", FORECAST, document))
    assert "вне режима" in session.measurements()["warnings"][0]


def test_scenario_runs_say_there_are_no_measurements():
    session = session_for("baseline")
    assert session.measurements()["live"] is False
