import pytest

from neftecode.application.ports import LLMError, LLMMessage, ResponseEffectProvider, ToolCall, ToolSpec
from neftecode.infrastructure.response.unavailable import UnavailableResponseEffect


def test_tool_message_must_reference_a_call():
    with pytest.raises(ValueError):
        LLMMessage("tool", "{}")
    assert LLMMessage("tool", "{}", tool_call_id="c1").tool_call_id == "c1"


def test_only_assistant_carries_tool_calls():
    with pytest.raises(ValueError):
        LLMMessage("user", "x", tool_calls=(ToolCall("c1", "t"),))
    with pytest.raises(ValueError):
        LLMMessage("robot", "x")


def test_tool_spec_requires_object_schema_and_plain_name():
    with pytest.raises(ValueError):
        ToolSpec("bad name", "x")
    with pytest.raises(ValueError):
        ToolSpec("ok", "x", {"type": "array"})
    assert ToolSpec("get_margins", "x").parameters["type"] == "object"


def test_unknown_error_kind_degrades_to_provider():
    error = LLMError("weird", "boom", retryable=True, code="7")
    assert error.kind == "provider" and error.retryable and error.code == "7"


def test_unavailable_response_effect_names_the_blocker():
    provider: ResponseEffectProvider = UnavailableResponseEffect()
    answer = provider.effect({}, 1.0)
    assert answer["available"] is False
    assert "T11" in answer["reason"] and "F26" in answer["reason"]
    assert not any(key in answer for key in ("sulfur_mid", "beta_tau", "effect_mid"))
