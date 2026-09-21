import pytest

from neftecode.domain.shared.primitives import HOLD, RECOMMEND_SCENARIO, REFUSE
from neftecode.infrastructure.llm.demo_policy import demo_llm, quality_policy, reliability_policy
from neftecode.infrastructure.llm.scripted import PolicyLLM, ScriptedLLM, call, context_of, respond, tool_results

from _agentic_support import agentic_decide, legacy_decide, session_for, without_agentic


def finalize(action, codes=("done",), candidate=None, refs=("context:legacy",), summary="итог"):
    arguments = {"action": action, "reason_codes": list(codes), "summary": summary, "evidence_refs": list(refs)}
    if candidate:
        arguments["candidate_id"] = candidate
    return respond(call("finalize", **arguments))


def tools_by_agent(decision):
    trace = decision["agentic"]["trace"]
    return {agent: [e["tool_name"] for e in trace if e["kind"] == "tool" and e["agent"] == agent]
            for agent in ("orchestrator", "quality", "reliability")}


def test_keep_legacy_returns_the_legacy_decision_unchanged():
    decision = agentic_decide("baseline", ScriptedLLM([finalize("keep_legacy", ("legacy_ok",))]))
    assert without_agentic(decision) == legacy_decide("baseline")
    assert decision["agentic"]["outcome"] == "confirmed_legacy"
    assert decision["agentic"]["legacy_decision_id"] == decision["decision_id"]


def test_keep_legacy_on_the_first_turn_is_a_short_two_event_run_not_an_anomaly():
    """Регрессия T02/I4 (task-pool.md, problems.md #11): наблюдался прогон агентного этапа за
    0,6 с с 2 событиями в трассе на той же модели, что и обычный прогон 2:11. Причина — не кэш,
    не гонка потоков и не оборванный вызов: модель вправе вызвать finalize(keep_legacy) прямо на
    первом шаге, не спрашивая специалистов (orchestrator.py не требует их согласия для этой ветки,
    в отличие от refuse). Трасса тогда состоит ровно из двух событий: llm_call и final. Фиксируем
    структуру такого прогона и явный диагностический маркер, который отличает его от сбоя."""
    decision = agentic_decide("baseline", ScriptedLLM([finalize("keep_legacy", ("legacy_ok",))]))
    trace = decision["agentic"]["trace"]
    # Основа прогона — ровно то, что видели в браузере: один вызов модели и её финальный ответ.
    # Третье событие — наш диагностический маркер (см. ниже), не ещё один вызов LLM.
    assert [(e["agent"], e["kind"]) for e in trace[:2]] == [("orchestrator", "llm_call"), ("orchestrator", "final")]
    assert decision["agentic"]["outcome"] == "confirmed_legacy"
    assert decision["agentic"]["opinions"] == []
    assert decision["agentic"]["keep_legacy_grounded"] is False
    assert trace[-1]["decision"] == "keep_legacy_ungrounded"
    assert trace[-1]["reason_codes"] == ["no_specialist_consultation"]


def test_keep_legacy_after_a_consult_is_marked_grounded():
    def consult_then_keep(role, messages, tools):
        if role == "quality":
            if not tool_results(messages):
                return respond(call("get_quality_margins", candidate_id="hold"))
            return respond(call("submit_opinion", verdict="OK", risk_level="low", confidence=0.8,
                                evidence_refs=["get_quality_margins:hold"],
                                candidate_verdicts={"hold": "OK"}, reasons=[]))
        if not tool_results(messages):
            return respond(call("ask_quality_agent", candidate_ids=["hold"]))
        return finalize("keep_legacy", ("legacy_ok",), refs=("ask_quality_agent:hold",))

    decision = agentic_decide("baseline", PolicyLLM(consult_then_keep))
    assert decision["agentic"]["outcome"] == "confirmed_legacy"
    assert decision["agentic"]["opinions"] != []
    assert decision["agentic"]["keep_legacy_grounded"] is True
    assert not any(e for e in decision["agentic"]["trace"] if e.get("decision") == "keep_legacy_ungrounded")


def test_screen_payload_marks_opinion_confidence_as_uncalibrated_self_report():
    opinions = agentic_decide("sour_crude", demo_llm())["agentic"]["opinions"]
    assert opinions
    for item in opinions:
        assert isinstance(item["confidence"], float)
        assert item["confidence_kind"] == "llm_self_report" and item["confidence_calibrated"] is False


def test_demo_policy_paths_differ_by_situation():
    calm = agentic_decide("baseline", demo_llm())
    sour = agentic_decide("sour_crude", demo_llm())
    impossible = agentic_decide("no_feasible", demo_llm())
    assert tools_by_agent(calm) == {"orchestrator": ["ask_quality_agent", "ask_reliability_agent"],
                                    "quality": ["get_quality_margins"], "reliability": ["get_setpoint_changes"]}
    assert tools_by_agent(sour) == {
        "orchestrator": ["ask_quality_agent", "search_candidates", "rank_allowed", "ask_reliability_agent"],
        "quality": ["get_quality_margins", "get_forecast_and_uncertainty", "get_tank_projection"],
        "reliability": ["get_setpoint_changes", "get_robustness"]}
    assert tools_by_agent(impossible)["orchestrator"] == ["search_candidates", "rank_allowed"]
    assert calm["status"] == HOLD and calm["agentic"]["outcome"] == "confirmed_legacy"
    assert impossible["status"] == REFUSE and impossible["agentic"]["outcome"] == "confirmed_legacy"


def test_constraint_driven_replan_releases_a_gate_feasible_plan():
    decision = agentic_decide("sour_crude", demo_llm())
    assert decision["agentic"]["outcome"] == "selected"
    assert decision["status"] == RECOMMEND_SCENARIO and decision["gate"]["feasible"] is True
    assert decision["agentic"]["constraints_applied"][0]["type"] == "min_quality_margin"
    agents = [t["agent"] for t in decision["trace"]]
    assert agents == ["optimizer", "agentic", "lookahead", "quality", "reliability", "robustness", "tank_estimate"]
    margin = decision["agentic"]["constraints_applied"][0]["value"]
    sulfur = [c for c in decision["gate"]["checks"] if c["constraint_id"] == "quality.sulfur_mgkg"]
    assert all(c["limit"] - c["observed"] >= margin - 1e-9 for c in sulfur)
    assert decision["agentic"]["trace"][-1]["kind"] == "guard"


def test_select_is_resolved_by_rank_not_by_the_model():
    session = session_for("baseline")
    ranked = session.rank_allowed()["selected"]
    other = next(cid for cid in session.allowed_ids() if cid != ranked)
    llm = ScriptedLLM([finalize("select", ("prefer_other",), candidate=other, refs=("context:candidates",))])
    decision = agentic_decide("baseline", llm)
    assert decision["agentic"]["llm_choice_overridden"] is True
    assert decision["status"] == HOLD and decision["selected_plan"]["plan_id"] == ranked == "hold"


def test_a_selection_outside_the_allowed_set_falls_back_instead_of_being_obeyed():
    llm = ScriptedLLM([finalize("select", ("prefer_other",), candidate="ghost", refs=("context:candidates",))])
    decision = agentic_decide("baseline", llm)
    assert decision["agentic"]["outcome"] == "fallback"
    assert decision["agentic"]["llm_choice_overridden"] is False


def test_quality_veto_of_hold_moves_to_the_next_allowed_plan():
    def veto_hold(role, messages, tools):
        if role == "quality":
            results = tool_results(messages)
            if not results:
                return respond(call("get_quality_margins", candidate_id="hold"))
            return respond(call("submit_opinion", verdict="REJECT", risk_level="high", confidence=0.9,
                                evidence_refs=["get_quality_margins:hold"], candidate_verdicts={"hold": "REJECT"},
                                reasons=[{"code": "cetane_margin_thin", "text": "Запас цетанового числа 0.65"}]))
        results = tool_results(messages)
        if not results:
            return respond(call("ask_quality_agent", candidate_ids=["hold"]))
        return finalize("keep_legacy", ("quality_rejected_legacy",), refs=("ask_quality_agent:hold",))

    decision = agentic_decide("baseline", PolicyLLM(veto_hold))
    assert decision["agentic"]["vetoed_candidates"] == {"hold": ["quality"]}
    assert decision["status"] == RECOMMEND_SCENARIO and decision["selected_plan"]["plan_id"] != "hold"
    assert decision["gate"]["feasible"] is True


def test_grounded_refusal_is_more_conservative():
    def reject_all(role, messages, tools):
        if role == "quality":
            if not tool_results(messages):
                return respond(call("get_quality_margins", candidate_id="c0025"))
            return respond(call("submit_opinion", verdict="REJECT", risk_level="high", confidence=0.9,
                                evidence_refs=["get_quality_margins:c0025"],
                                reasons=[{"code": "thin_sulfur_margin", "text": "Запас по сере 0.4 мг/кг"}]))
        if not tool_results(messages):
            return respond(call("ask_quality_agent", candidate_ids=["c0025"]))
        return finalize("refuse", ("quality_rejected",), refs=("ask_quality_agent:c0025",))

    decision = agentic_decide("sour_crude", PolicyLLM(reject_all))
    assert decision["status"] == REFUSE and decision["selected_plan"] is None
    assert decision["refusal"]["kind"] == "agent_rejected"
    assert decision["agentic"]["outcome"] == "refused"


def test_consultation_and_replan_limits_are_enforced():
    llm = ScriptedLLM([respond(call("search_candidates", constraints=[])),
                       respond(call("search_candidates", constraints=[])),
                       finalize("keep_legacy", refs=("context:legacy",))])
    decision = agentic_decide("sour_crude", llm)
    errors = [e for e in decision["agentic"]["trace"] if e["kind"] == "tool" and e.get("decision") == "error"]
    assert errors and errors[0]["reason_codes"] == ["replan_limit_reached"]
    assert decision["agentic"]["budget"]["replans"] == 1
