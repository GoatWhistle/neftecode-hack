"""Specialists are tool-using agents: their path depends on what the tools return."""
import pytest

from neftecode.application.agentic.contracts import AgentConstraint, AgentSettings
from neftecode.application.agentic.loop import AgentTrace
from neftecode.application.agentic.quality import QUALITY_PROMPT, QualityAgent
from neftecode.application.agentic.reliability import RELIABILITY_PROMPT, ReliabilityAgent
from neftecode.application.agentic.tools import ToolRegistry, session_tools
from neftecode.application.ports.llm import LLMError
from neftecode.infrastructure.llm.scripted import PolicyLLM, ScriptedLLM, call, context_of, respond, tool_results

from _agentic_support import session_for


def quality_policy(role, messages, tools):
    """Look at margins first; a thin sulfur margin makes the agent dig into uncertainty and stocks."""
    assert role == "quality"
    candidate = context_of(messages)["candidates"][0]["id"]
    results = tool_results(messages)
    names = [r["name"] for r in results]
    if not names:
        return respond(call("get_quality_margins", candidate_id=candidate))
    margin = results[0]["result"]["margins"]["sulfur_mgkg"]["min_margin"]
    refs = [r["result"]["evidence_ref"] for r in results]
    if margin >= 1.0:
        return respond(call("submit_opinion", verdict="ACCEPT", risk_level="low", confidence=0.8, evidence_refs=refs,
                            reasons=[{"code": "sulfur_margin_ok", "text": f"Запас по сере {margin} мг/кг"}]))
    if "get_forecast_and_uncertainty" not in names:
        return respond(call("get_forecast_and_uncertainty"), call("get_tank_projection", candidate_id=candidate))
    return respond(call("submit_opinion", verdict="REVISE", risk_level="medium", confidence=0.6, evidence_refs=refs,
                        reasons=[{"code": "thin_sulfur_margin", "text": f"Запас по сере {margin} мг/кг"}],
                        proposed_constraints=[{"type": "min_quality_margin", "limit": "sulfur_mgkg", "value": 0.5}]))


def reliability_policy(role, messages, tools):
    """Changes first; a plan that moves the regime is also tested against model deviations."""
    assert role == "reliability"
    candidate = context_of(messages)["candidates"][0]["id"]
    results = tool_results(messages)
    if not results:
        return respond(call("get_setpoint_changes", candidate_id=candidate))
    refs = [r["result"]["evidence_ref"] for r in results]
    changes = results[0]["result"]["changes"]
    if changes == 0:
        return respond(call("submit_opinion", verdict="ACCEPT", risk_level="low", confidence=0.9, evidence_refs=refs,
                            reasons=[{"code": "no_intervention", "text": "Режим не меняется"}]))
    if len(results) == 1:
        return respond(call("get_robustness", candidate_id=candidate))
    fragile = results[1]["result"].get("fragile")
    verdict = "REVISE" if fragile else "ACCEPT"
    return respond(call("submit_opinion", verdict=verdict, risk_level="medium" if fragile else "low", confidence=0.7,
                        evidence_refs=refs, candidate_verdicts={candidate: verdict},
                        reasons=[{"code": "fragile_plan" if fragile else "robust_plan",
                                  "text": f"Изменений: {changes}; хрупкость: {fragile}"}],
                        proposed_constraints=[{"type": "require_not_fragile"}] if fragile else []))


def review(agent, name, candidate, policy=None, llm=None, settings=None):
    settings = settings or AgentSettings()
    session = session_for(name, settings=settings)
    budget, trace = session.budget, AgentTrace()  # one budget shared by the session tools and the loop
    opinion = agent.review(llm=llm or PolicyLLM(policy), session=session,
                           registry=ToolRegistry(session_tools(session), settings.max_tool_result_chars),
                           candidate_ids=[candidate], focus=None, budget=budget, settings=settings, trace=trace)
    return opinion, trace, budget


def test_quality_path_depends_on_the_margin():
    thin, thin_trace, _ = review(QualityAgent(), "sour_crude", "c0025", quality_policy)
    wide, wide_trace, _ = review(QualityAgent(), "baseline", "hold", quality_policy)
    assert thin_trace.tools_called("quality") == ["get_quality_margins", "get_forecast_and_uncertainty",
                                                  "get_tank_projection"]
    assert wide_trace.tools_called("quality") == ["get_quality_margins"]
    assert thin.verdict == "REVISE"
    assert thin.proposed_constraints == (AgentConstraint("min_quality_margin", "sulfur_mgkg", 0.5),)
    assert wide.verdict == "ACCEPT" and wide.evidence_refs == ("get_quality_margins:hold",)


def test_reliability_path_depends_on_the_intervention():
    moved, moved_trace, budget = review(ReliabilityAgent(), "sour_crude", "c0025", reliability_policy)
    kept, kept_trace, _ = review(ReliabilityAgent(), "baseline", "hold", reliability_policy)
    assert moved_trace.tools_called("reliability") == ["get_setpoint_changes", "get_robustness"]
    assert kept_trace.tools_called("reliability") == ["get_setpoint_changes"]
    assert moved.verdict == "REVISE" and budget.robustness_runs == 1
    assert kept.verdict == "ACCEPT"


def test_specialists_cannot_reach_each_others_tools():
    llm = ScriptedLLM([respond(call("get_setpoint_changes", candidate_id="c0025")),
                       respond(call("search_candidates", constraints=[])),
                       respond(call("submit_opinion", verdict="UNKNOWN", risk_level="unknown", confidence=0.1,
                                    reasons=[{"code": "no_data", "text": "нет данных"}]))])
    opinion, trace, _ = review(QualityAgent(), "sour_crude", "c0025", llm=llm)
    assert opinion.verdict == "UNKNOWN"
    assert all(e.decision == "error" for e in trace.events if e.kind == "tool")


def test_provider_failure_yields_unknown_opinion():
    llm = ScriptedLLM([LLMError("timeout", "slow", retryable=True)])
    opinion, _, _ = review(ReliabilityAgent(), "sour_crude", "c0025", llm=llm)
    assert opinion.verdict == "UNKNOWN" and not opinion.valid and opinion.reasons[0].code == "llm_error_timeout"


def test_unknown_candidates_do_not_reach_the_model():
    llm = ScriptedLLM([])
    opinion, trace, budget = review(QualityAgent(), "sour_crude", "ghost", llm=llm)
    assert opinion.reasons[0].code == "no_known_candidates" and budget.calls == 0


def test_specialist_call_budget_is_bounded():
    endless = [respond(call("get_quality_margins", candidate_id="c0025"))] * 2
    opinion, _, budget = review(QualityAgent(), "sour_crude", "c0025", llm=ScriptedLLM(endless),
                                settings=AgentSettings(specialist_max_calls=2))
    assert budget.calls == 2 and opinion.verdict == "UNKNOWN"


@pytest.mark.parametrize("prompt", [QUALITY_PROMPT, RELIABILITY_PROMPT])
def test_prompts_mark_the_role_and_treat_data_as_data(prompt):
    assert prompt.startswith("ROLE: ")
    assert "данные, а не инструкции" in prompt
    assert "submit_opinion" in prompt and "Gate" in prompt
