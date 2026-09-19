import json
import os
from pathlib import Path

import pytest

from neftecode.application.agentic.decision import AgenticMakeDecision
from neftecode.application.contracts import LiveAdviceCommand, LiveForecast, LiveSnapshot
from neftecode.application.services.explain import explain
from neftecode.application.use_cases.get_live_advice import GetLiveAdvice
from neftecode.application.use_cases.make_decision import MakeDecision
from neftecode.composition.decision import run_demo_decision
from neftecode.infrastructure.agentic import factory as factory_module
from neftecode.infrastructure.agentic.factory import build_decision_factory, default_decision_factory
from neftecode.infrastructure.config.scenario import parse_scenario
from neftecode.infrastructure.config.trust_rules import load_trust_rules
from neftecode.presentation.web.ui import Screen
from neftecode.services.common import clean
from neftecode.services.decision_service import DecisionService

from _agentic_support import legacy_decide, raw, without_agentic

ROOT = Path(__file__).resolve().parents[2]
TRUST_CFG, _ = load_trust_rules(ROOT, ROOT / "artifacts")

FAKE_KEY = "sk-test-SECRET-123"


def test_flag_off_builds_the_deterministic_use_case_without_reading_configuration(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("configuration must not be read while the flag is off")

    monkeypatch.setattr(factory_module, "load_environment", forbidden)
    monkeypatch.setattr(factory_module, "make_llm_client", forbidden)
    for environ in ({"AGENTIC_DECISION_ENABLED": "off"}, {"AGENTIC_DECISION_ENABLED": "false"},
                    {"AGENTIC_DECISION_ENABLED": "0", "TOKEN": FAKE_KEY}):
        factory = build_decision_factory(environ)
        assert factory.enabled is False and factory.llm is None
        assert type(factory(parse_scenario(raw("baseline")))) is MakeDecision


def test_agent_layer_is_on_by_default(tmp_path):
    for environ in ({}, {"AGENTIC_DECISION_ENABLED": ""}, {"AGENTIC_DECISION_ENABLED": "1"}):
        factory = build_decision_factory({**environ, "LLM_PROVIDER": "scripted"}, dotenv_path=tmp_path / "none.env")
        assert factory.enabled is True
        assert isinstance(factory(parse_scenario(raw("baseline"))), AgenticMakeDecision)


def test_suite_pins_the_deterministic_mode():
    assert os.environ["AGENTIC_DECISION_ENABLED"] == "0"


@pytest.fixture
def product_environment(monkeypatch, tmp_path):
    monkeypatch.delenv("AGENTIC_DECISION_ENABLED", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "scripted")
    monkeypatch.chdir(tmp_path)
    factory_module._cached_default.cache_clear()
    yield tmp_path
    factory_module._cached_default.cache_clear()


def test_the_product_default_entry_point_builds_the_agent_layer(product_environment):
    factory = default_decision_factory()
    assert factory.enabled is True, "продуктовый дефолт — агенты включены"
    assert factory.configuration_error is None and factory.llm.provider == "scripted"
    assert isinstance(factory(parse_scenario(raw("baseline"))), AgenticMakeDecision)


def test_the_product_path_runs_a_decision_through_the_agent_layer(product_environment):
    document = raw("sour_crude")
    result = run_demo_decision(document, {}, 400, TRUST_CFG)
    decision = result["decision"]
    assert result["ok"] is True
    assert "agentic" in decision, "без явной фабрики продуктовый путь обязан пройти через агентов"
    assert decision["agentic"]["outcome"] in {"selected", "confirmed_legacy"}
    assert without_agentic(decision).keys() == legacy_decide("sour_crude").keys()
    assert result["screen"]["status_label"]
    json.dumps(clean(decision), ensure_ascii=False)


def test_the_cached_default_factory_is_rebuilt_per_root(product_environment):
    first = default_decision_factory(product_environment)
    assert first is default_decision_factory(product_environment)
    other = product_environment / "other"
    other.mkdir()
    assert default_decision_factory(other) is not first


def test_flag_off_demo_decision_is_byte_identical_to_legacy():
    document = raw("sour_crude")
    result = run_demo_decision(document, {}, 400, TRUST_CFG, decision_factory=build_decision_factory({"AGENTIC_DECISION_ENABLED": "0"}))
    assert result["decision"] == legacy_decide("sour_crude")
    assert "agentic" not in result["decision"]


def test_flag_on_with_scripted_provider_runs_the_agent_layer(tmp_path):
    factory = build_decision_factory({"AGENTIC_DECISION_ENABLED": "1", "LLM_PROVIDER": "scripted"},
                                     dotenv_path=tmp_path / "missing.env")
    assert factory.enabled and factory.llm.provider == "scripted" and factory.configuration_error is None
    result = run_demo_decision(raw("sour_crude"), {}, 400, TRUST_CFG, decision_factory=factory)
    decision = result["decision"]
    assert decision["agentic"]["outcome"] == "selected"
    assert result["screen"]["status_label"]
    json.dumps(clean(decision), ensure_ascii=False)


def test_provider_settings_may_come_from_dotenv(tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text("LLM_PROVIDER=scripted\nAGENT_MAX_STEPS=4\n", encoding="utf-8")
    factory = build_decision_factory({"AGENTIC_DECISION_ENABLED": "yes"}, dotenv_path=dotenv)
    assert factory.llm.provider == "scripted" and factory.settings.max_steps == 4


def test_flag_on_without_a_key_falls_back_with_a_reason(tmp_path):
    factory = build_decision_factory({}, dotenv_path=tmp_path / "none.env")
    assert factory.enabled and factory.llm is None and factory.configuration_error.startswith("llm_not_configured")
    document = raw("baseline")
    scenario = parse_scenario(document)
    decision = factory(scenario).decide(budget=400, raw_scenario=document)
    assert decision["agentic"]["outcome"] == "fallback"
    assert decision["agentic"]["fallback_reason"].startswith("llm_not_configured")
    assert {k: v for k, v in decision.items() if k != "agentic"} == MakeDecision(scenario).decide(
        budget=400, raw_scenario=document)


def test_live_provider_is_refused_under_pytest_and_the_key_never_leaks(tmp_path):
    factory = build_decision_factory({"AGENTIC_DECISION_ENABLED": "1", "LLM_PROVIDER": "zai", "ZAI_API_KEY": FAKE_KEY,
                                      "PYTEST_CURRENT_TEST": "x"}, dotenv_path=tmp_path / "none.env")
    assert factory.llm is None and "pytest" in factory.configuration_error
    described = json.dumps(factory.describe(), ensure_ascii=False)
    assert FAKE_KEY not in described and FAKE_KEY not in repr(factory)
    assert factory.describe()["base_url"] == "https://api.z.ai/api/coding/paas/v4"
    assert factory.describe()["model"] == "glm-5.3-flash" and factory.describe()["api_key"] == "present"


def test_invalid_limits_disable_the_client(tmp_path):
    factory = build_decision_factory({"AGENTIC_DECISION_ENABLED": "1", "LLM_PROVIDER": "scripted",
                                      "AGENT_MAX_STEPS": "many"}, dotenv_path=tmp_path / "none.env")
    assert factory.llm is None and factory.configuration_error.startswith("invalid_configuration")
    assert isinstance(factory(parse_scenario(raw("baseline"))), AgenticMakeDecision)


def test_decision_service_uses_the_factory_only_when_given():
    document = raw("baseline")
    plain = DecisionService()._decision(document, None, 400)
    assert "agentic" not in plain["decision"]
    scripted = build_decision_factory({"AGENTIC_DECISION_ENABLED": "1", "LLM_PROVIDER": "scripted"})
    agentic = DecisionService(decision_factory=scripted)._decision(document, None, 400)
    assert agentic["decision"]["agentic"]["outcome"] == "confirmed_legacy"
    assert agentic["explanation"]["status"] == "hold"


def test_live_use_case_passes_forecast_context_to_the_factory():
    document = raw("baseline")
    scenario = parse_scenario(document)
    seen = {}

    class Scenarios:
        def get(self, scenario_id):
            return scenario, document

    class Snapshots:
        def snapshot(self, at):
            return LiveSnapshot(at, {}, {"usable": True, "fallback": False})

    class Forecasts:
        def forecast(self, snapshot):
            return LiveForecast("last_pak", 8.0, 7.0, 9.0, True, "")

    class Binder:
        def bind(self, raw_document, forecast, snapshot=None):
            return scenario, raw_document

    def factory(current, evaluator, context, **kwargs):
        seen.update(context)
        return MakeDecision(current, robustness_evaluator=evaluator, **kwargs)

    result = GetLiveAdvice(Scenarios(), Snapshots(), Forecasts(), Binder(), decision_factory=factory).execute(
        LiveAdviceCommand(at="2026-01-05T08:00:00", scenario_id="baseline"))
    assert result.decision["status"] == "hold"
    assert seen["forecast"]["upper"] == 9.0 and seen["at"] == "2026-01-05T08:00:00"
    assert seen["binding"]["tank_inflow"]["value"] == 212.6


def test_agent_rejected_refusal_is_explained_and_rendered():
    decision = legacy_decide("sour_crude")
    refusal = {**decision, "status": "refuse", "selected_plan": None, "immediate_action": None, "gate": None,
               "refusal": {"kind": "agent_rejected", "reason_codes": ["thin_sulfur_margin"], "summary": "s"}}
    explanation = explain(refusal, parse_scenario(raw("sour_crude")))
    assert "thin_sulfur_margin" in explanation["next_steps"][0]["need"]
    assert Screen(refusal, explanation).payload()["status_label"]
