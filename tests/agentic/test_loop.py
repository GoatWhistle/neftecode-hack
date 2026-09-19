import json

import pytest

from neftecode.application.agentic.budget import AgentBudget
from neftecode.application.agentic.contracts import AgentSettings, parse_opinion
from neftecode.application.agentic.loop import AgentTrace, run_tool_loop
from neftecode.application.agentic.tools import QUALITY_TOOLS, SUBMIT_OPINION, ToolRegistry, session_tools
from neftecode.application.ports.llm import LLMError
from neftecode.infrastructure.llm.scripted import ScriptedLLM, call, respond

from _agentic_support import session_for

CANDIDATES = ("c0025",)


def opinion(verdict="ACCEPT", refs=("get_quality_margins:c0025",)):
    return {"verdict": verdict, "risk_level": "low", "confidence": 0.8, "evidence_refs": list(refs),
            "reasons": [{"code": "margin_ok", "text": "Запас достаточен", "candidate_id": "c0025"}]}


@pytest.fixture(scope="module")
def session():
    return session_for("sour_crude")


def run(session, llm, settings=None, max_calls=3):
    settings = settings or AgentSettings()
    budget = AgentBudget(settings)
    trace = AgentTrace()
    result = run_tool_loop(role="quality", llm=llm, system_prompt="ROLE: quality", context_text="DATA {}",
                           context_refs=("context:candidates",),
                           registry=ToolRegistry(session_tools(session), settings.max_tool_result_chars),
                           allowlist=QUALITY_TOOLS, final_tool=SUBMIT_OPINION,
                           parse_final=lambda raw, ev: parse_opinion("quality", raw, candidates=CANDIDATES, evidence=ev),
                           max_calls=max_calls, budget=budget, settings=settings, trace=trace)
    return result, trace, budget


def test_tool_then_final(session):
    llm = ScriptedLLM([respond(call("get_quality_margins", candidate_id="c0025")),
                       respond(call("submit_opinion", **opinion()))])
    result, trace, budget = run(session, llm)
    assert result.stop_reason == "final" and result.final.verdict == "ACCEPT"
    assert trace.tools_called("quality") == ["get_quality_margins"]
    assert budget.calls == 2
    assert "get_quality_margins:c0025" in result.evidence


def test_final_without_obtained_evidence_is_downgraded(session):
    llm = ScriptedLLM([respond(call("submit_opinion", **opinion()))])
    result, _, _ = run(session, llm)
    assert result.final.verdict == "UNKNOWN"


def test_text_answer_is_repaired_locally(session):
    llm = ScriptedLLM([respond(content="Итог:\n```json\n" + json.dumps(opinion(refs=("context:candidates",))) + "\n```")])
    result, trace, _ = run(session, llm)
    assert result.stop_reason == "final" and result.final.verdict == "ACCEPT"
    assert trace.events[-1].reason_codes == ("local_repair",)


def test_invalid_final_gets_one_correction_then_stops(session):
    bad = respond(call("submit_opinion", verdict="MAYBE"))
    llm = ScriptedLLM([bad, bad, respond(call("submit_opinion", **opinion()))])
    result, _, budget = run(session, llm)
    assert result.stop_reason == "invalid_final" and result.final is None
    assert budget.calls == 2 and llm.remaining == 1


def test_invalid_final_then_valid_final_is_accepted(session):
    llm = ScriptedLLM([respond(call("submit_opinion", verdict="MAYBE")),
                       respond(call("submit_opinion", **opinion(refs=("context:candidates",))))])
    assert run(session, llm)[0].final.verdict == "ACCEPT"


def test_disallowed_and_unknown_tools_are_answered_with_errors(session):
    llm = ScriptedLLM([respond(call("get_setpoint_changes", candidate_id="c0025"), call("shell", cmd="ls")),
                       respond(call("submit_opinion", **opinion(refs=("context:candidates",))))])
    result, trace, _ = run(session, llm)
    assert result.final.verdict == "ACCEPT"
    errors = [e for e in trace.events if e.kind == "tool"]
    assert [e.decision for e in errors] == ["error", "error"]
    assert errors[0].reason_codes == ("tool_not_allowed",)


def test_last_call_offers_only_the_final_tool(session):
    endless = [respond(call("get_quality_margins", candidate_id="c0025"))] * 3
    llm = ScriptedLLM(endless)
    result, _, budget = run(session, llm, max_calls=3)
    assert result.stop_reason == "max_calls" and budget.calls == 3
    assert llm.calls[-1]["tools"] == ["submit_opinion"]
    assert "get_quality_margins" in llm.calls[0]["tools"]


def test_extra_tool_calls_in_one_response_are_dropped(session):
    many = respond(*[call("get_quality_margins", candidate_id="c0025")] * 5)
    llm = ScriptedLLM([many, respond(call("submit_opinion", **opinion()))])
    result, trace, _ = run(session, llm, settings=AgentSettings(max_tool_calls_per_response=2))
    assert len(trace.tools_called()) == 2
    assert any(e.decision == "extra_tool_calls_dropped" for e in trace.events)


def test_provider_error_stops_the_loop(session):
    llm = ScriptedLLM([LLMError("rate_limit", "slow down", retryable=True)])
    result, trace, _ = run(session, llm)
    assert result.stop_reason == "llm_error:rate_limit" and result.error.kind == "rate_limit"
    assert trace.events[-1].kind == "fallback"


def test_global_budget_stops_before_the_call(session):
    llm = ScriptedLLM([respond(call("get_quality_margins", candidate_id="c0025"))])
    result, _, budget = run(session, llm, settings=AgentSettings(max_llm_calls=1))
    assert result.stop_reason == "budget:llm_calls" and budget.calls == 1 and llm.remaining == 0


def test_usage_is_accumulated(session):
    llm = ScriptedLLM([respond(call("submit_opinion", **opinion(refs=("context:candidates",))), usage=(100, 20))])
    _, trace, budget = run(session, llm)
    assert budget.usage["total_tokens"] == 120
    assert trace.events[0].usage == {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}


def test_provider_error_code_and_message_reach_the_trace(session):
    llm = ScriptedLLM([LLMError("quota", "HTTP 429, код 1113: insufficient balance", code="1113")])
    result, trace, _ = run(session, llm)
    event = trace.events[-1]
    assert result.stop_reason == "llm_error:quota"
    assert event.reason_codes == ("1113",) and "1113" in event.tool_result_summary
