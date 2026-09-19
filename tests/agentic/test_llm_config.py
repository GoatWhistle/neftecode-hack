import pytest

from neftecode.infrastructure.llm.config import (LLMSettings, Secret, agent_limits_from_env, agentic_enabled,
                                                 llm_settings_from_env, load_environment, parse_dotenv, truthy)

FAKE = "sk-test-SECRET-123"


def test_dotenv_parsing_handles_comments_quotes_export_and_case():
    text = "\n".join([
        "# comment", "", "export ZAI_MODEL=glm-x", "token=abc", 'QUOTED="a b # c"', "SINGLE='x'",
        "MISMATCH=\"y'", "no_equals_line", "  SPACED  =  v  ",
    ])
    values = parse_dotenv(text)
    assert values == {"ZAI_MODEL": "glm-x", "token": "abc", "QUOTED": "a b # c", "SINGLE": "x",
                      "MISMATCH": "\"y'", "SPACED": "v"}
    assert "TOKEN" not in values


def test_real_environment_wins_over_dotenv(tmp_path):
    path = tmp_path / ".env"
    path.write_text("ZAI_MODEL=from-file\nLLM_MAX_TOKENS=100\n", encoding="utf-8")
    merged = load_environment({"ZAI_MODEL": "from-env"}, path)
    assert merged == {"ZAI_MODEL": "from-env", "LLM_MAX_TOKENS": "100"}
    assert load_environment({"A": "1"}, tmp_path / "missing.env") == {"A": "1"}
    assert load_environment({"A": "1"}, None) == {"A": "1"}


def test_zai_key_aliases_in_priority_order():
    zai = {"LLM_PROVIDER": "zai"}
    assert llm_settings_from_env({**zai, "ZAI_API_KEY": "k1", "TOKEN": "k2", "token": "k3"}).api_key.reveal() == "k1"
    assert llm_settings_from_env({**zai, "ZAI_API_KEY": " ", "TOKEN": "k2", "token": "k3"}).api_key.reveal() == "k2"
    assert llm_settings_from_env({**zai, "token": "k3"}).api_key.reveal() == "k3"
    assert not llm_settings_from_env(zai).api_key


def test_local_plant_model_is_an_option():
    local = llm_settings_from_env({"LLM_PROVIDER": "local"})
    assert (local.provider, local.model, local.base_url) == ("local", "", "http://127.0.0.1:8000/v1")
    assert not local.api_key
    configured = llm_settings_from_env({"LLM_PROVIDER": "local", "LOCAL_LLM_MODEL": "qwen-27b",
                                        "LOCAL_LLM_BASE_URL": "http://llm:9000/v1"})
    assert (configured.model, configured.base_url) == ("qwen-27b", "http://llm:9000/v1")


def test_default_provider_is_the_zai_coding_plan():
    assert llm_settings_from_env({}).provider == "zai"
    settings = llm_settings_from_env({"LLM_PROVIDER": "zai"})
    assert (settings.provider, settings.model, settings.base_url) == (
        "zai", "glm-5.3-flash", "https://api.z.ai/api/coding/paas/v4")
    assert (settings.request_timeout_s, settings.max_retries, settings.max_tokens, settings.temperature) == (
        120.0, 1, 6144, 0.2)
    assert settings.allow_general_endpoint is False
    assert llm_settings_from_env({"ZAI_ALLOW_GENERAL_ENDPOINT": "Yes"}).allow_general_endpoint is True


def test_other_providers():
    openai = llm_settings_from_env({"LLM_PROVIDER": "openai", "OPENAI_API_KEY": FAKE})
    assert (openai.base_url, openai.model, openai.api_key.reveal()) == ("https://api.openai.com/v1", "", FAKE)
    anthropic = llm_settings_from_env({"LLM_PROVIDER": "anthropic", "ANTHROPIC_MODEL": "m"})
    assert (anthropic.base_url, anthropic.model, bool(anthropic.api_key)) == ("https://api.anthropic.com", "m",
                                                                              False)
    assert llm_settings_from_env({"LLM_PROVIDER": "scripted"}).provider == "scripted"


def test_secret_never_prints():
    secret = Secret(FAKE)
    assert repr(secret) == str(secret) == "Secret(***)"
    assert f"{secret}" == "Secret(***)" and secret.reveal() == FAKE and secret and not Secret("")
    settings = llm_settings_from_env({"LLM_PROVIDER": "zai", "ZAI_API_KEY": FAKE,
                                      "ZAI_BASE_URL": "https://h/api/coding/v4?x=1"})
    assert FAKE not in repr(settings) and FAKE not in str(settings)
    described = settings.describe()
    assert described["api_key"] == "present" and FAKE not in str(described)
    assert described["base_url"] == "https://h/api/coding/v4"
    assert set(described) >= {"provider", "model", "base_url", "max_tokens", "request_timeout_s", "max_retries"}
    assert LLMSettings("zai", "m", "u").describe()["api_key"] == "missing"


@pytest.mark.parametrize("name, value", [
    ("LLM_REQUEST_TIMEOUT_SECONDS", "abc"), ("LLM_REQUEST_TIMEOUT_SECONDS", "0"),
    ("LLM_MAX_RETRIES", "-1"), ("LLM_MAX_RETRIES", "1.5"), ("LLM_MAX_TOKENS", "0"),
    ("LLM_TEMPERATURE", "nan"), ("LLM_TEMPERATURE", "-0.1"),
])
def test_invalid_numbers_name_the_variable(name, value):
    with pytest.raises(ValueError, match=name) as caught:
        llm_settings_from_env({name: value, "ZAI_API_KEY": FAKE})
    assert FAKE not in str(caught.value)


def test_valid_number_overrides():
    settings = llm_settings_from_env({"LLM_REQUEST_TIMEOUT_SECONDS": "5.5", "LLM_MAX_RETRIES": "0",
                                      "LLM_MAX_TOKENS": "512", "LLM_TEMPERATURE": "0"})
    assert (settings.request_timeout_s, settings.max_retries, settings.max_tokens, settings.temperature) == (
        5.5, 0, 512, 0.0)


def test_agent_limits_defaults_and_overrides():
    assert agent_limits_from_env({}) == {
        "max_steps": 5, "specialist_max_calls": 3, "max_specialist_consults": 2, "max_llm_calls": 12,
        "max_replans": 1, "timeout_s": 600, "max_candidates": 5, "max_context_chars": 12000,
        "max_tool_result_chars": 2500, "max_robustness_runs": 2, "max_tool_calls_per_response": 3,
    }
    limits = agent_limits_from_env({"AGENT_MAX_STEPS": "7", "AGENT_TIMEOUT_SECONDS": "30.5"})
    assert limits["max_steps"] == 7 and limits["timeout_s"] == 30.5


@pytest.mark.parametrize("value", ["0", "-3", "many", "2.5"])
def test_agent_limits_reject_invalid_values(value):
    with pytest.raises(ValueError, match="AGENT_MAX_LLM_CALLS"):
        agent_limits_from_env({"AGENT_MAX_LLM_CALLS": value})


def test_agent_layer_is_on_unless_explicitly_switched_off():
    assert agentic_enabled({})
    for value in ("1", "true", "YES", "On", " on ", "", "2"):
        assert agentic_enabled({"AGENTIC_DECISION_ENABLED": value})
    assert truthy("on") and not truthy("")
    for value in ("0", "false", "No", " OFF "):
        assert not agentic_enabled({"AGENTIC_DECISION_ENABLED": value})


def test_asdict_of_settings_does_not_unwrap_the_secret():
    import dataclasses

    from neftecode.infrastructure.llm.config import LLMSettings, Secret

    settings = LLMSettings("zai", "glm-5.3-flash", "https://api.z.ai/api/coding/paas/v4", Secret("sk-test-SECRET-123"))
    assert "sk-test-SECRET-123" not in str(dataclasses.asdict(settings))
    assert "sk-test-SECRET-123" not in repr(settings)
