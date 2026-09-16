"""LLM adapters against a fake urlopen: request shape, parsing, error mapping, retries and the factory guard."""
import io
import json
import os
import urllib.error
import urllib.request

import pytest

from neftecode.application.ports.llm import LLMError, LLMMessage, ToolCall, ToolSpec
from neftecode.infrastructure.llm import (AnthropicClient, LLMSettings, OpenAICompatibleClient, Secret,
                                          make_llm_client, map_http_error)

FAKE = "sk-test-SECRET-123"
ZAI_URL = "https://api.z.ai/api/coding/paas/v4"
TOOL = ToolSpec("get_margins", "Маржа по кандидатам", {"type": "object", "properties": {"k": {"type": "integer"}}})


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return self.payload if isinstance(self.payload, bytes) else json.dumps(self.payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeHTTP:
    """Replays outcomes in order: dict/bytes -> 200 response, (status, body) -> HTTPError, exception -> raised."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append({"url": request.full_url, "headers": dict(request.header_items()),
                              "body": json.loads(request.data), "timeout": timeout, "method": request.get_method()})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        if isinstance(outcome, tuple):
            status, body = outcome
            raw = body if isinstance(body, bytes) else json.dumps(body).encode()
            raise urllib.error.HTTPError(request.full_url, status, "err", {}, io.BytesIO(raw))
        return FakeResponse(outcome)


@pytest.fixture
def http(monkeypatch):
    def install(*outcomes):
        fake = FakeHTTP(*outcomes)
        monkeypatch.setattr(urllib.request, "urlopen", fake)
        return fake
    return install


def zai(sleeps=None, **kwargs):
    ticks = iter(range(100))
    return OpenAICompatibleClient("zai", ZAI_URL, "glm-5.3-flash", Secret(FAKE),
                                  sleep=(sleeps.append if sleeps is not None else lambda s: None),
                                  clock=lambda: float(next(ticks)), **kwargs)


def completion(message, finish="stop", usage=None):
    return {"choices": [{"message": message, "finish_reason": finish}],
            "usage": usage or {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14}}


CONVERSATION = (
    LLMMessage("system", "Ты оркестратор"),
    LLMMessage("user", "Выбери план"),
    LLMMessage("assistant", "", tool_calls=(ToolCall("c1", "get_margins", '{"k": 3}'),
                                            ToolCall("c2", "get_margins", '{"k": 4}'))),
    LLMMessage("tool", '{"margin": 1}', tool_call_id="c1"),
    LLMMessage("tool", '{"margin": 2}', tool_call_id="c2"),
)


def test_zai_request_shape(http):
    fake = http(completion({"role": "assistant", "content": "ok"}))
    zai().chat(CONVERSATION, (TOOL,), max_tokens=321, timeout_s=7.5)
    request = fake.requests[0]
    assert request["url"] == "https://api.z.ai/api/coding/paas/v4/chat/completions"
    assert request["method"] == "POST" and request["timeout"] == 7.5
    headers = {key.lower(): value for key, value in request["headers"].items()}
    assert headers["authorization"] == f"Bearer {FAKE}"
    assert headers["content-type"] == headers["accept"] == "application/json"
    body = request["body"]
    assert {"thinking", "response_format"}.isdisjoint(body)
    assert (body["model"], body["max_tokens"], body["temperature"], body["stream"]) == (
        "glm-5.3-flash", 321, 0.2, False)
    assert body["tool_choice"] == "auto"
    assert body["tools"] == [{"type": "function", "function": {
        "name": "get_margins", "description": TOOL.description, "parameters": TOOL.parameters}}]
    assert body["messages"][:2] == [{"role": "system", "content": "Ты оркестратор"},
                                    {"role": "user", "content": "Выбери план"}]
    assert body["messages"][2] == {"role": "assistant", "content": "", "tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": "get_margins", "arguments": '{"k": 3}'}},
        {"id": "c2", "type": "function", "function": {"name": "get_margins", "arguments": '{"k": 4}'}}]}
    assert body["messages"][3:] == [{"role": "tool", "content": '{"margin": 1}', "tool_call_id": "c1"},
                                    {"role": "tool", "content": '{"margin": 2}', "tool_call_id": "c2"}]


def test_no_tools_means_no_tool_choice(http):
    fake = http(completion({"content": "ok"}))
    zai().chat([LLMMessage("user", "hi")], max_tokens=10, timeout_s=1)
    assert {"tools", "tool_choice"}.isdisjoint(fake.requests[0]["body"])


def test_parses_tool_calls_usage_and_discards_reasoning(http):
    http(completion({"role": "assistant", "content": None, "reasoning_content": "hidden-chain-of-thought",
                     "tool_calls": [{"id": "t1", "type": "function",
                                     "function": {"name": "get_margins", "arguments": '{"k": 5}'}},
                                    {"id": "t2", "function": {"name": "finalize", "arguments": {"plan": "A"}}}]},
                    finish="tool_calls"))
    response = zai().chat([LLMMessage("user", "hi")], (TOOL,), max_tokens=10, timeout_s=1)
    assert response.content == "" and response.finish_reason == "tool_calls"
    assert response.tool_calls == (ToolCall("t1", "get_margins", '{"k": 5}'),
                                   ToolCall("t2", "finalize", '{"plan": "A"}'))
    assert (response.usage.prompt_tokens, response.usage.completion_tokens, response.usage.total_tokens) == (
        10, 4, 14)
    assert (response.provider, response.model, response.latency_s) == ("zai", "glm-5.3-flash", 1.0)
    assert "hidden-chain-of-thought" not in repr(response)
    assert not hasattr(response, "reasoning_content")


@pytest.mark.parametrize("payload", [b"<html>not json</html>", {"choices": []}, {"id": "x"}])
def test_malformed_response_is_bad_response(http, payload):
    fake = http(payload, payload)
    with pytest.raises(LLMError) as caught:
        zai().chat([LLMMessage("user", "hi")], max_tokens=10, timeout_s=1)
    assert caught.value.kind == "bad_response" and not caught.value.retryable
    assert len(fake.requests) == 1


def test_401_is_auth_and_not_retried(http):
    fake = http((401, {"error": {"code": "1001", "message": "Authorization Token Missing"}}))
    with pytest.raises(LLMError) as caught:
        zai().chat([LLMMessage("user", "hi")], max_tokens=10, timeout_s=1)
    assert caught.value.kind == "auth" and len(fake.requests) == 1


def test_rate_limit_1302_is_retried_once_then_raised(http):
    sleeps = []
    body = {"error": {"code": "1302", "message": "High concurrency"}}
    fake = http((429, body), (429, body))
    with pytest.raises(LLMError) as caught:
        zai(sleeps).chat([LLMMessage("user", "hi")], max_tokens=10, timeout_s=1)
    assert (caught.value.kind, caught.value.retryable, caught.value.code) == ("rate_limit", True, "1302")
    assert len(fake.requests) == 2 and sleeps == [1.0]


@pytest.mark.parametrize("code", ["1113", "1313", "1315"])
def test_quota_and_plan_codes_are_not_retried(http, code):
    fake = http((429, {"error": {"code": code, "message": "Insufficient balance"}}), completion({"content": "x"}))
    with pytest.raises(LLMError) as caught:
        zai().chat([LLMMessage("user", "hi")], max_tokens=10, timeout_s=1)
    assert (caught.value.kind, caught.value.retryable) == ("quota", False)
    assert len(fake.requests) == 1


def test_server_error_retries_then_succeeds(http):
    sleeps = []
    fake = http((500, b"Internal Server Error"), completion({"content": "готово"}))
    response = zai(sleeps).chat([LLMMessage("user", "hi")], max_tokens=10, timeout_s=1)
    assert response.content == "готово" and len(fake.requests) == 2 and sleeps == [1.0]


def test_backoff_grows_with_more_retries(http):
    sleeps = []
    fake = http((503, b""), (502, b""), (504, b""))
    with pytest.raises(LLMError):
        zai(sleeps, max_retries=2).chat([LLMMessage("user", "hi")], max_tokens=10, timeout_s=1)
    assert sleeps == [1.0, 2.0] and len(fake.requests) == 3


def test_timeout_and_network_errors_are_retryable(http):
    fake = http(TimeoutError("timed out"), urllib.error.URLError(TimeoutError()))
    with pytest.raises(LLMError) as caught:
        zai().chat([LLMMessage("user", "hi")], max_tokens=10, timeout_s=1)
    assert (caught.value.kind, caught.value.retryable) == ("timeout", True) and len(fake.requests) == 2
    http(urllib.error.URLError("Name or service not known"), urllib.error.URLError("refused"))
    with pytest.raises(LLMError) as caught:
        zai().chat([LLMMessage("user", "hi")], max_tokens=10, timeout_s=1)
    assert (caught.value.kind, caught.value.retryable) == ("network", True)


def test_finish_reason_length_and_sensitive(http):
    http(completion({"content": ""}, finish="length"))
    with pytest.raises(LLMError) as caught:
        zai().chat([LLMMessage("user", "hi")], max_tokens=10, timeout_s=1)
    assert (caught.value.kind, caught.value.retryable) == ("bad_response", False)
    fake = http(completion({"content": "..."}, finish="sensitive"))
    with pytest.raises(LLMError) as caught:
        zai().chat([LLMMessage("user", "hi")], max_tokens=10, timeout_s=1)
    assert (caught.value.kind, caught.value.retryable) == ("provider", False) and len(fake.requests) == 1


def test_errors_never_contain_the_key(http):
    http((401, {"error": {"code": "1000", "message": f"bad key {FAKE}"}}))
    client = zai()
    with pytest.raises(LLMError) as caught:
        client.chat([LLMMessage("user", "hi")], max_tokens=10, timeout_s=1)
    for text in (str(caught.value), repr(caught.value), repr(client), str(client.describe())):
        assert FAKE not in text
    assert caught.value.__cause__ is None


def test_error_messages_are_short():
    error = map_http_error(400, json.dumps({"error": {"code": "1214", "message": "x" * 5000}}))
    assert error.kind == "bad_request" and len(str(error)) < 260


@pytest.mark.parametrize("status, body, kind, retryable", [
    (429, {}, "rate_limit", True),
    (429, {"error": {"type": "insufficient_quota", "code": "insufficient_quota", "message": "quota"}}, "quota", False),
    (401, {"error": {"type": "invalid_request_error", "code": "invalid_api_key", "message": "no"}}, "auth", False),
    (529, {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}, "overloaded", True),
    (400, {"type": "error", "error": {"type": "invalid_request_error", "message": "bad"}}, "bad_request", False),
    (400, {"error": {"code": 1261, "message": "Prompt too long"}}, "bad_request", False),
    (200, {"error": {"code": "1305", "message": "busy"}}, "overloaded", True),
    (500, {"error": {"code": "1301", "message": "unsafe"}}, "provider", False),
])
def test_error_mapping_table(status, body, kind, retryable):
    error = map_http_error(status, json.dumps(body))
    assert (error.kind, error.retryable) == (kind, retryable)


def test_openai_base_url(http):
    fake = http(completion({"content": "hi"}))
    client = OpenAICompatibleClient("openai", "https://api.openai.com/v1/", "gpt-x", Secret(FAKE))
    assert client.chat([LLMMessage("user", "hi")], max_tokens=10, timeout_s=1).provider == "openai"
    assert fake.requests[0]["url"] == "https://api.openai.com/v1/chat/completions"


def test_anthropic_request_shape_and_parsing(http):
    fake = http({"content": [{"type": "text", "text": "Смотрю маржу. "},
                             {"type": "tool_use", "id": "tu1", "name": "get_margins", "input": {"k": 2}}],
                 "stop_reason": "tool_use", "usage": {"input_tokens": 20, "output_tokens": 5}})
    ticks = iter([0.0, 0.25])
    client = AnthropicClient("https://api.anthropic.com", "claude-x", Secret(FAKE), sleep=lambda s: None,
                             clock=lambda: next(ticks))
    messages = (*CONVERSATION[:2], LLMMessage("system", "Кратко"),
                LLMMessage("assistant", "думаю", tool_calls=(ToolCall("c1", "get_margins", '{"k": 3}'),
                                                             ToolCall("c2", "get_margins", "not json"))),
                *CONVERSATION[3:])
    response = client.chat(messages, (TOOL,), max_tokens=100, timeout_s=3)
    request = fake.requests[0]
    headers = {key.lower(): value for key, value in request["headers"].items()}
    assert request["url"] == "https://api.anthropic.com/v1/messages"
    assert headers["x-api-key"] == FAKE and headers["anthropic-version"] == "2023-06-01"
    assert "authorization" not in headers
    body = request["body"]
    assert body["system"] == "Ты оркестратор\n\nКратко"
    assert body["tools"] == [{"name": "get_margins", "description": TOOL.description, "input_schema": TOOL.parameters}]
    assert body["tool_choice"] == {"type": "auto"} and body["max_tokens"] == 100
    assert body["messages"] == [
        {"role": "user", "content": "Выбери план"},
        {"role": "assistant", "content": [
            {"type": "text", "text": "думаю"},
            {"type": "tool_use", "id": "c1", "name": "get_margins", "input": {"k": 3}},
            {"type": "tool_use", "id": "c2", "name": "get_margins", "input": {}}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "c1", "content": '{"margin": 1}'},
            {"type": "tool_result", "tool_use_id": "c2", "content": '{"margin": 2}'}]},
    ]
    assert response.content == "Смотрю маржу. " and response.finish_reason == "tool_calls"
    assert response.tool_calls == (ToolCall("tu1", "get_margins", '{"k": 2}'),)
    assert (response.usage.prompt_tokens, response.usage.completion_tokens, response.usage.total_tokens) == (
        20, 5, 25)
    assert (response.provider, response.latency_s) == ("anthropic", 0.25)


def test_anthropic_overloaded_is_retried(http):
    fake = http((529, {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}),
                {"content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn", "usage": {}})
    client = AnthropicClient("https://api.anthropic.com", "claude-x", Secret(FAKE), sleep=lambda s: None)
    response = client.chat([LLMMessage("user", "hi")], max_tokens=10, timeout_s=1)
    assert response.finish_reason == "stop" and len(fake.requests) == 2
    assert "tool_choice" not in fake.requests[0]["body"]


def live_env(**extra):
    return {"PYTEST_CURRENT_TEST": "x", "LLM_ALLOW_LIVE_IN_TESTS": "1", **extra}


def test_factory_refuses_under_pytest(monkeypatch):
    monkeypatch.delenv("LLM_ALLOW_LIVE_IN_TESTS", raising=False)
    assert "PYTEST_CURRENT_TEST" in os.environ
    settings = LLMSettings("zai", "glm-5.3-flash", ZAI_URL, Secret(FAKE))
    with pytest.raises(LLMError, match="pytest") as caught:
        make_llm_client(settings)
    assert caught.value.kind == "not_configured"


def test_factory_guards(http):
    fake = http()
    general = LLMSettings("zai", "glm-5.3-flash", "https://api.z.ai/api/paas/v4", Secret(FAKE))
    with pytest.raises(LLMError, match="ZAI_ALLOW_GENERAL_ENDPOINT") as caught:
        make_llm_client(general, live_env())
    assert caught.value.kind == "not_configured"
    allowed = LLMSettings("zai", "glm-5.3-flash", "https://api.z.ai/api/paas/v4", Secret(FAKE),
                          allow_general_endpoint=True)
    assert make_llm_client(allowed, live_env()).provider == "zai"
    with pytest.raises(LLMError, match="ZAI_API_KEY") as caught:
        make_llm_client(LLMSettings("zai", "glm-5.3-flash", ZAI_URL), live_env())
    assert caught.value.kind == "not_configured"
    with pytest.raises(LLMError, match="OPENAI_MODEL"):
        make_llm_client(LLMSettings("openai", "", "https://api.openai.com/v1", Secret(FAKE)), live_env())
    for provider in ("scripted", "mystery"):
        with pytest.raises(LLMError) as caught:
            make_llm_client(LLMSettings(provider, "m", "u", Secret(FAKE)), live_env())
        assert caught.value.kind == "not_configured" and FAKE not in str(caught.value)
    with pytest.raises(LLMError, match="scripted"):
        make_llm_client(LLMSettings("scripted", "scripted", ""), {})
    assert fake.requests == []


def test_factory_builds_clients_without_network(http):
    fake = http()
    client = make_llm_client(LLMSettings("zai", "glm-5.3-flash", ZAI_URL, Secret(FAKE), max_retries=0), live_env())
    assert isinstance(client, OpenAICompatibleClient) and client.max_retries == 0
    anthropic = make_llm_client(LLMSettings("anthropic", "claude-x", "https://api.anthropic.com", Secret(FAKE)),
                                live_env())
    assert isinstance(anthropic, AnthropicClient)
    assert fake.requests == []


def test_local_provider_needs_no_key_and_sends_no_authorization(monkeypatch):
    import json as _json

    from neftecode.infrastructure.llm.config import llm_settings_from_env
    from neftecode.infrastructure.llm.factory import make_llm_client

    captured = {}

    class Reply:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return _json.dumps({"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}).encode()

    def fake(request, timeout=None):
        captured["url"] = request.full_url
        captured["headers"] = {k.lower(): v for k, v in request.header_items()}
        return Reply()

    monkeypatch.setattr("urllib.request.urlopen", fake)
    settings = llm_settings_from_env({"LLM_PROVIDER": "local", "LOCAL_LLM_MODEL": "qwen-27b"})
    client = make_llm_client(settings, {"LLM_ALLOW_LIVE_IN_TESTS": "1"})
    from neftecode.application.ports.llm import LLMMessage
    reply = client.chat([LLMMessage("user", "x")], max_tokens=10, timeout_s=1)
    assert reply.content == "ok" and client.provider == "local"
    assert captured["url"] == "http://127.0.0.1:8000/v1/chat/completions"
    assert "authorization" not in captured["headers"]


def test_local_provider_without_a_model_is_not_configured():
    from neftecode.application.ports.llm import LLMError
    from neftecode.infrastructure.llm.config import llm_settings_from_env
    from neftecode.infrastructure.llm.factory import make_llm_client

    with pytest.raises(LLMError, match="LOCAL_LLM_MODEL"):
        make_llm_client(llm_settings_from_env({"LLM_PROVIDER": "local"}), {"LLM_ALLOW_LIVE_IN_TESTS": "1"})
