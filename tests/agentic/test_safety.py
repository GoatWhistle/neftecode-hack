"""Adversarial model behaviour never produces a plan the gate did not accept, and failures fall back."""
from dataclasses import replace

import pytest

from neftecode.application.agentic import decision as decision_module
from neftecode.application.agentic.contracts import AgentSettings
from neftecode.application.contracts import DataRejection
from neftecode.application.ports.llm import LLMError
from neftecode.domain.advisory.entities import CheckResult, GateResult
from neftecode.domain.shared.primitives import FAIL, HOLD, RECOMMEND_SCENARIO, REFUSE
from neftecode.infrastructure.llm.scripted import PolicyLLM, ScriptedLLM, call, respond, tool_results

from _agentic_support import agentic_decide, agentic_for, legacy_decide, raw, session_for, without_agentic

SCENARIOS = ["baseline", "sour_crude", "ample_reserve", "no_feasible"]


def finalize(action, candidate=None, codes=("x",), refs=("context:legacy",)):
    arguments = {"action": action, "reason_codes": list(codes), "summary": "s", "evidence_refs": list(refs)}
    if candidate:
        arguments["candidate_id"] = candidate
    return respond(call("finalize", **arguments))


def infeasible_id(name):
    session = session_for(name)
    return next(cid for cid, e in session.evaluations.items() if not e.feasible)


def assert_released_plan_passes_the_gate(decision):
    if decision["status"] in (HOLD, RECOMMEND_SCENARIO):
        assert decision["gate"]["feasible"] is True
        assert all(c["status"] == "pass" for c in decision["gate"]["checks"])


@pytest.mark.parametrize("name", ["baseline", "sour_crude", "ample_reserve"])
def test_selecting_a_gate_rejected_plan_is_never_released(name):
    bad = infeasible_id(name)
    decision = agentic_decide(name, ScriptedLLM([finalize("select", bad, refs=("context:candidates",))]))
    assert decision["agentic"]["outcome"] == "fallback"
    assert decision["agentic"]["fallback_reason"] == "selection_not_allowed"
    assert without_agentic(decision) == legacy_decide(name)
    assert (decision["selected_plan"] or {}).get("plan_id") != bad


def test_selecting_an_unknown_plan_falls_back():
    decision = agentic_decide("sour_crude", ScriptedLLM([finalize("select", "c9999")]))
    assert decision["agentic"]["fallback_reason"] == "selection_not_allowed"
    assert without_agentic(decision) == legacy_decide("sour_crude")


def test_a_loosening_constraint_is_rejected_and_changes_nothing():
    llm = ScriptedLLM([
        respond(call("search_candidates", constraints=[{"type": "min_quality_margin", "limit": "sulfur_mgkg", "value": -5},
                                                       {"type": "raise_limit", "value": 12}])),
        finalize("keep_legacy")])
    decision = agentic_decide("sour_crude", llm)
    assert decision["agentic"]["constraints_applied"] == []
    tool = next(e for e in decision["agentic"]["trace"] if e.get("tool_name") == "search_candidates")
    assert tool["decision"] == "error"  # schema enum rejects the unknown type before any evaluation
    assert without_agentic(decision) == legacy_decide("sour_crude")


def test_refusal_without_evidence_is_ignored():
    decision = agentic_decide("baseline", ScriptedLLM([finalize("refuse", codes=("i_feel_like_it",))]))
    assert decision["status"] == HOLD and decision["agentic"]["fallback_reason"] == "refuse_without_evidence"


@pytest.mark.parametrize("name", SCENARIOS)
def test_endless_tool_calls_stop_at_the_step_limit(name):
    endless = PolicyLLM(lambda role, messages, tools: respond(call("rank_allowed")))
    settings = AgentSettings(max_steps=3, max_llm_calls=12)
    decision = agentic_decide(name, endless, settings)
    assert decision["agentic"]["outcome"] == "fallback"
    assert decision["agentic"]["fallback_reason"].startswith("orchestrator_no_final")
    assert decision["agentic"]["budget"]["llm_calls"] <= 3
    assert without_agentic(decision) == legacy_decide(name)


@pytest.mark.parametrize("garbage", ["не JSON", '{"action": "approve_everything"}', "```json\n{broken\n```"])
def test_garbage_answers_fall_back(garbage):
    decision = agentic_decide("sour_crude", PolicyLLM(lambda role, messages, tools: respond(content=garbage)))
    assert decision["agentic"]["outcome"] == "fallback"
    assert without_agentic(decision) == legacy_decide("sour_crude")


@pytest.mark.parametrize("kind", ["timeout", "rate_limit", "quota", "auth", "bad_response", "network"])
def test_provider_errors_fall_back(kind):
    decision = agentic_decide("ample_reserve", ScriptedLLM([LLMError(kind, "boom")]))
    assert decision["agentic"]["fallback_reason"] == f"orchestrator_no_final:llm_error:{kind}"
    assert without_agentic(decision) == legacy_decide("ample_reserve")


def test_unexpected_exceptions_fall_back():
    decision = agentic_decide("baseline", ScriptedLLM([RuntimeError("bug in provider"), finalize("keep_legacy")]))
    assert decision["agentic"]["fallback_reason"] == "unexpected_error:RuntimeError"
    assert without_agentic(decision) == legacy_decide("baseline")


def test_specialist_failure_does_not_fail_the_decision():
    def policy(role, messages, tools):
        if role == "quality":
            raise LLMError("overloaded", "busy", retryable=True)
        if not tool_results(messages):
            return respond(call("ask_quality_agent", candidate_ids=["hold"]))
        return finalize("keep_legacy", refs=("ask_quality_agent:hold",))

    decision = agentic_decide("baseline", PolicyLLM(policy))
    assert decision["agentic"]["outcome"] == "confirmed_legacy"
    assert decision["agentic"]["opinions"][0]["verdict"] == "UNKNOWN"
    assert decision["agentic"]["vetoed_candidates"] == {}


def test_data_refusal_skips_the_model_entirely():
    llm = ScriptedLLM([])
    state = {"decision_time": "2026-01-05T08:00:00", "lab_value": None, "lab_usable": False, "pak_frozen": True,
             "pak_usable": False, "pak_value": 8.0, "pak_age_minutes": 10.0, "telemetry_missing_fraction": 0.0}
    decision = agentic_decide("baseline", llm, state=state)
    assert decision["status"] == REFUSE and decision["agentic"]["outcome"] == "skipped"
    rejected = agentic_decide("baseline", llm, data_rejection=DataRejection("snapshot rejected", ("lab",)))
    assert rejected["agentic"]["outcome"] == "skipped" and llm.calls == []


def test_missing_client_falls_back_without_calls():
    document = raw("baseline")
    maker = agentic_for("baseline", None, document=document)
    maker.configuration_error = "llm_not_configured: не задан ключ"
    decision = maker.decide(budget=400, raw_scenario=document)
    assert decision["agentic"]["fallback_reason"] == "llm_not_configured: не задан ключ"
    assert without_agentic(decision) == legacy_decide("baseline")


def _veto_then_keep(role, messages, tools):
    if role == "quality":
        if not tool_results(messages):
            return respond(call("get_quality_margins", candidate_id="hold"))
        return respond(call("submit_opinion", verdict="REJECT", risk_level="high", confidence=0.9,
                            evidence_refs=["get_quality_margins:hold"], candidate_verdicts={"hold": "REJECT"},
                            reasons=[{"code": "veto", "text": "veto"}]))
    if not tool_results(messages):
        return respond(call("ask_quality_agent", candidate_ids=["hold"]))
    return finalize("keep_legacy", refs=("ask_quality_agent:hold",))


def test_llm_accept_with_gate_fail_is_fail_at_final_recheck(monkeypatch):
    """A plan the agents like still refuses when the gate fails at the final re-check."""
    document = raw("baseline")
    maker = agentic_for("baseline", PolicyLLM(_veto_then_keep), document=document)
    original_search = maker.maker._search
    original = maker.maker.planner.evaluate
    searched = {}

    def search(*args, **kwargs):
        outcome = original_search(*args, **kwargs)
        searched["done"] = searched.get("done", 0) + 1
        return outcome

    def evaluate(*args, **kwargs):
        evaluation = original(*args, **kwargs)
        if searched.get("done", 0) >= 2:  # after the legacy run and the agent session search
            failed = CheckResult("quality.sulfur_mgkg", FAIL, 11.0, 10.0, 0.0, reason="forced gate failure")
            return replace(evaluation, gate=GateResult(evaluation.gate.plan_id, (failed,)))
        return evaluation

    monkeypatch.setattr(maker.maker, "_search", search)
    monkeypatch.setattr(maker.maker.planner, "evaluate", evaluate)
    decision = maker.decide(budget=400, raw_scenario=document)
    assert decision["status"] == REFUSE and decision["refusal"]["kind"] == "final_recheck_failed"
    assert decision["selected_plan"] is None


def test_independent_guard_refuses_when_a_fresh_gate_disagrees(monkeypatch):
    class BrokenPlanner:
        def __init__(self, scenario):
            pass

        def evaluate(self, plan, confirmed=(), **kwargs):
            failed = CheckResult("inventory.reserve", FAIL, -1.0, 0.0, 1.0, reason="fresh gate disagrees")
            return type("E", (), {"feasible": False, "gate": GateResult(plan.plan_id, (failed,))})()

    monkeypatch.setattr(decision_module, "PlanOperation", BrokenPlanner)
    decision = agentic_decide("baseline", PolicyLLM(_veto_then_keep))
    assert decision["status"] == REFUSE and decision["refusal"]["kind"] == "final_recheck_failed"
    assert decision["refusal"]["examples"] == ["fresh gate disagrees"]
    assert decision["agentic"]["trace"][-1]["decision"] == "fail"


def accept_everything(role, messages, tools):
    if role in ("quality", "reliability"):
        return respond(call("submit_opinion", verdict="ACCEPT", risk_level="low", confidence=1.0,
                            evidence_refs=["context:candidates"], reasons=[{"code": "all_good", "text": "ok"}]))
    results = tool_results(messages)
    if not results:
        return respond(call("search_candidates", constraints=[]))
    if len(results) == 1:
        return respond(call("rank_allowed"))
    selected = results[-1]["result"].get("selected")
    return finalize("select", selected, refs=("rank_allowed:",)) if selected else finalize("keep_legacy")


@pytest.mark.parametrize("name", SCENARIOS)
def test_accept_everything_never_releases_what_legacy_gate_refused(name):
    legacy = legacy_decide(name)
    decision = agentic_decide(name, PolicyLLM(accept_everything))
    assert_released_plan_passes_the_gate(decision)
    if legacy["status"] == REFUSE:
        assert decision["status"] == REFUSE or decision["gate"]["feasible"] is True


def test_agentic_key_is_added_after_the_decision_id():
    decision = agentic_decide("baseline", ScriptedLLM([finalize("keep_legacy")]))
    assert decision["decision_id"] == legacy_decide("baseline")["decision_id"]
    assert set(decision) - set(legacy_decide("baseline")) == {"agentic"}


def test_no_secret_like_values_in_the_agentic_block():
    decision = agentic_decide("sour_crude", PolicyLLM(accept_everything))
    text = repr(decision["agentic"])
    for marker in ("api_key", "Authorization", "Bearer", "x-api-key", "reasoning_content"):
        assert marker not in text


def test_a_negative_margin_is_rejected_by_the_contract_even_when_the_schema_passes():
    llm = ScriptedLLM([
        respond(call("search_candidates", constraints=[{"type": "min_quality_margin", "limit": "sulfur_mgkg",
                                                        "value": -5}])),
        finalize("keep_legacy")])
    decision = agentic_decide("sour_crude", llm)
    tool = next(e for e in decision["agentic"]["trace"] if e.get("tool_name") == "search_candidates")
    assert tool["decision"] == "ok" and "constraints_rejected" in tool["tool_result_summary"]
    assert decision["agentic"]["constraints_applied"] == []
    assert decision["agentic"]["outcome"] == "confirmed_legacy"
