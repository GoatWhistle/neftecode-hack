"""P5: результат ядра — отдельным предварительным событием, затем ровно один итог агентного этапа."""
import itertools

import pytest

from neftecode.application.agentic.contracts import AgentSettings
from neftecode.application.contracts import DataRejection
from neftecode.application.ports.llm import LLMError
from neftecode.application.progress import reporting_to
from neftecode.infrastructure.llm.scripted import PolicyLLM, ScriptedLLM, call, respond
from neftecode.presentation.web.progress import decision_stream

from _agentic_support import BUDGET, agentic_for, raw, without_agentic, legacy_decide


def collect(name, llm, settings=None, clock=None, **kwargs):
    maker = agentic_for(name, llm, settings)
    if clock is not None:
        maker.clock = clock
    events = []
    with reporting_to(events.append):
        decision = maker.decide(budget=BUDGET, raw_scenario=raw(name), **kwargs)
    return decision, events


def finalize_keep():
    return respond(call("finalize", action="keep_legacy", reason_codes=["ok"], summary="s",
                        evidence_refs=["context:legacy"]))


def test_core_result_precedes_agent_events_and_is_marked_preliminary():
    decision, events = collect("sour_crude", ScriptedLLM([finalize_keep()]))
    kinds = [e["kind"] for e in events]
    core = next(e for e in events if e["kind"] == "core")
    assert kinds.index("core") < next(i for i, e in enumerate(events)
                                      if e["kind"] == "stage" and e.get("stage") == "agents")
    assert core["phase"] == "preliminary" and "не окончательный" in core["note"]
    assert core["decision_id"] == decision["agentic"]["legacy_decision_id"]
    assert decision["agentic"]["terminal"]["kind"] == "completed"
    timing = decision["agentic"]["timing"]
    assert timing["core_s"] >= 0 and timing["total_s"] >= timing["core_s"]


def test_data_refusal_has_no_core_preview_and_no_llm_calls():
    llm = ScriptedLLM([])
    decision, events = collect("baseline", llm,
                               data_rejection=DataRejection("нет данных", ("лабораторный анализ серы",)))
    assert not any(e["kind"] == "core" for e in events)
    assert decision["agentic"]["terminal"]["kind"] == "skipped_data_refusal"
    assert decision["agentic"]["terminal"]["domain_impossibility_proven"] is True


def test_deadline_stops_new_calls_and_is_not_called_domain_impossibility():
    ticks = itertools.count()
    clock = lambda: next(ticks) * 7.0  # каждое чтение часов — +7 с, без реального ожидания
    llm = PolicyLLM(lambda role, messages, tools: respond(call("rank_allowed")))
    decision, _ = collect("sour_crude", llm, AgentSettings(timeout_s=20.0), clock=clock)
    terminal = decision["agentic"]["terminal"]
    assert terminal["kind"] == "budget_timeout"
    assert terminal["domain_impossibility_proven"] is False
    assert decision["agentic"]["budget"]["llm_calls"] <= 3
    assert without_agentic(decision) == legacy_decide("sour_crude")


def test_call_budget_is_not_increased_to_get_an_answer():
    llm = PolicyLLM(lambda role, messages, tools: respond(call("rank_allowed")))
    decision, _ = collect("sour_crude", llm, AgentSettings(max_llm_calls=2))
    assert decision["agentic"]["budget"]["llm_calls"] == 2
    assert decision["agentic"]["terminal"]["kind"] in ("call_budget_exhausted", "agent_failure")


@pytest.mark.parametrize("kind", ["timeout", "rate_limit", "provider"])
def test_provider_error_terminal_keeps_usage_unknown(kind):
    decision, _ = collect("ample_reserve", ScriptedLLM([LLMError(kind, "boom")]))
    terminal = decision["agentic"]["terminal"]
    assert terminal["kind"] == "provider_error" and terminal["usage_complete"] is False
    assert decision["status"] != "refuse" or terminal["domain_impossibility_proven"]


def test_sse_carries_core_before_exactly_one_terminal_screen():
    maker = agentic_for("sour_crude", ScriptedLLM([finalize_keep()]))
    frames = [f.event for f in decision_stream(lambda: maker.decide(budget=BUDGET, raw_scenario=raw("sour_crude")),
                                                heartbeat_s=5.0)]
    assert frames.count("core") == 1 and frames.count("screen") == 1 and "failed" not in frames
    assert frames.index("core") < frames.index("screen")
    assert frames[-1] == "end"
