import time

import pytest

from neftecode.application.cancellation import CancellationError, CancellationToken, cancellation_with, check_cancelled
from neftecode.application.use_cases.make_decision import MakeDecision
from neftecode.infrastructure.config.scenario import load_scenario
from neftecode.infrastructure.llm.scripted import PolicyLLM, respond
from neftecode.presentation.web.progress import decision_stream

from _agentic_support import agentic_for, raw


def test_cancelled_before_start_does_not_begin_search():
    token = CancellationToken()
    token.cancel()
    maker = MakeDecision(load_scenario("config/scenarios/baseline.json"))
    with pytest.raises(CancellationError):
        with cancellation_with(token):
            maker.decide(budget=20)


def test_cancellation_stops_candidate_search_between_evaluations(monkeypatch):
    token = CancellationToken()
    maker = MakeDecision(load_scenario("config/scenarios/baseline.json"))
    original = maker._evaluate_plan
    evaluated = {"count": 0}

    def evaluate(*args, **kwargs):
        evaluated["count"] += 1
        result = original(*args, **kwargs)
        token.cancel()
        return result

    monkeypatch.setattr(maker, "_evaluate_plan", evaluate)
    with cancellation_with(token), pytest.raises(CancellationError):
        maker.decide(budget=50)
    assert evaluated["count"] == 1


def test_cancellation_after_llm_response_prevents_more_calls():
    token = CancellationToken()

    def cancel_after_call(role, messages, tools):
        token.cancel()
        return respond(content="{}")

    llm = PolicyLLM(cancel_after_call)
    maker = agentic_for("baseline", llm)
    with cancellation_with(token), pytest.raises(CancellationError):
        maker.decide(budget=400, raw_scenario=raw("baseline"))
    assert len(llm.calls) == 1


def test_closing_stream_cancels_worker_within_one_heartbeat():
    stopped = False

    def compute():
        nonlocal stopped
        try:
            while True:
                check_cancelled()
                time.sleep(0.001)
        finally:
            stopped = True

    stream = decision_stream(compute, heartbeat_s=0.01)
    assert next(stream).event == "phase"
    assert next(stream).event == "tick"
    stream.close()
    deadline = time.monotonic() + 0.5
    while not stopped and time.monotonic() < deadline:
        time.sleep(0.005)
    assert stopped is True
