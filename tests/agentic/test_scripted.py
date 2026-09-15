"""Deterministic model stand-ins and the network guard."""
import socket
import urllib.request

import pytest

from neftecode.application.ports.llm import LLMError, LLMMessage, ToolCall, ToolSpec
from neftecode.infrastructure.llm.scripted import (PolicyLLM, ScriptedLLM, call, context_of, respond, role_of,
                                                   tool_results)

SYSTEM = LLMMessage("system", "ROLE: quality\nПравила")
USER = LLMMessage("user", 'DATA:\n{"shortlist": ["hold"]}')
TOOLS = (ToolSpec("get_quality_margins", "x"),)


def ask(llm, messages=(SYSTEM, USER)):
    return llm.chat(list(messages), TOOLS, max_tokens=100, timeout_s=1)


def test_network_is_forbidden_in_agent_tests():
    with pytest.raises(AssertionError):
        urllib.request.urlopen("x")
    with pytest.raises(AssertionError):
        socket.create_connection(("127.0.0.1", 1))


def test_scripted_queue_replays_in_order_and_refuses_extra_calls():
    llm = ScriptedLLM([respond(call("get_quality_margins", candidate_id="hold")), LLMError("timeout", "slow"),
                       lambda messages, tools: respond(content="done")])
    first = ask(llm)
    assert first.provider == "scripted" and first.tool_calls[0].call_id == "call_1"
    assert first.tool_calls[0].arguments == '{"candidate_id": "hold"}'
    with pytest.raises(LLMError):
        ask(llm)
    assert ask(llm).content == "done"
    with pytest.raises(AssertionError):
        ask(llm)
    assert [c["role"] for c in llm.calls] == ["quality", "quality", "quality"]


def test_policy_reads_role_context_and_tool_results():
    seen = {}

    def policy(role, messages, tools):
        seen.update(role=role, context=context_of(messages), results=tool_results(messages))
        return respond(content="ok")

    history = [SYSTEM, USER,
               LLMMessage("assistant", tool_calls=(ToolCall("call_9", "get_quality_margins", '{"candidate_id":"hold"}'),)),
               LLMMessage("tool", '{"sulfur_mgkg": {"min_margin": 0.4}}', tool_call_id="call_9")]
    PolicyLLM(policy).chat(history, TOOLS, max_tokens=10, timeout_s=1)
    assert seen["role"] == "quality"
    assert seen["context"] == {"shortlist": ["hold"]}
    assert seen["results"] == [{"name": "get_quality_margins", "arguments": {"candidate_id": "hold"},
                                "result": {"sulfur_mgkg": {"min_margin": 0.4}}}]


def test_role_is_unknown_without_marker():
    assert role_of([LLMMessage("system", "no marker")]) == "unknown"
