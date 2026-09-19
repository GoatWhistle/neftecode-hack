import random

import pytest

from neftecode.application.agentic.contracts import AgentSettings
from neftecode.application.agentic.tools import ORCHESTRATOR_TOOLS, QUALITY_TOOLS, RELIABILITY_TOOLS
from neftecode.application.ports.llm import LLMError
from neftecode.application.use_cases.plan_operation import PlanCandidate, PlanOperation
from neftecode.domain.advisory.entities import PlanStep
from neftecode.domain.shared.primitives import DECISION_STATUSES, HOLD, RECOMMEND_SCENARIO, REFUSE
from neftecode.infrastructure.config.scenario import parse_scenario
from neftecode.infrastructure.llm.demo_policy import demo_llm
from neftecode.infrastructure.llm.scripted import PolicyLLM, call, context_of, respond

from _agentic_support import agentic_decide, legacy_decide, raw, session_for, without_agentic

SCENARIOS = ["baseline", "sour_crude", "ample_reserve", "no_feasible"]
SETTINGS = AgentSettings()


def fresh_gate_passes(name: str, decision: dict) -> bool:
    plan = decision["selected_plan"]
    candidate = PlanCandidate(plan["plan_id"], tuple(PlanStep.from_dict(s) for s in plan["steps"]), plan["changes"])
    return PlanOperation(parse_scenario(raw(name))).evaluate(candidate).feasible


def check_invariants(name: str, legacy: dict, decision: dict):
    info = decision["agentic"]
    assert decision["status"] in DECISION_STATUSES
    assert not (info["fallback_reason"] or "").startswith("unexpected_error"), info["fallback_reason"]
    assert info.get("budget", {}).get("llm_calls", 0) <= SETTINGS.max_llm_calls
    assert decision["commercial_release_allowed"] is False
    if decision["status"] in (HOLD, RECOMMEND_SCENARIO):
        assert decision["gate"]["feasible"] is True
        assert fresh_gate_passes(name, decision)
    else:
        assert decision["selected_plan"] is None
    if info["outcome"] in ("confirmed_legacy", "fallback", "skipped"):
        assert without_agentic(decision) == legacy


def random_policy(seed: int, candidates: list[str]):
    rng = random.Random(seed)
    ids = candidates + ["ghost", "hold"]

    def policy(role, messages, tools):
        names = [t.name for t in tools]
        pick = rng.random()
        if role in ("quality", "reliability"):
            if pick < 0.5 and len(names) > 1:
                name = rng.choice([n for n in (QUALITY_TOOLS if role == "quality" else RELIABILITY_TOOLS)])
                return respond(call(name, candidate_id=rng.choice(ids)))
            asked = [c["id"] for c in context_of(messages).get("candidates", [])]
            verdict = rng.choice(["ACCEPT", "REVISE", "REJECT", "UNKNOWN"])
            return respond(call("submit_opinion", verdict=verdict, risk_level=rng.choice(["low", "high"]),
                                confidence=rng.random(), evidence_refs=["context:candidates"],
                                candidate_verdicts={c: rng.choice(["ACCEPT", "REJECT"]) for c in asked},
                                reasons=[{"code": "random", "text": "случайный ответ"}],
                                proposed_constraints=[{"type": "max_changes", "value": rng.choice([0, 1, 2, 7])}]))
        shortlist = [c["id"] for c in context_of(messages).get("candidates", [])]
        ids_here = shortlist * 3 + ids
        if pick < 0.6 and len(names) > 1:
            name = rng.choice(ORCHESTRATOR_TOOLS)
            if name.startswith("ask_"):
                return respond(call(name, candidate_ids=rng.sample(ids_here, 2)))
            if name == "search_candidates":
                return respond(call(name, constraints=[rng.choice([
                    {"type": "forbid_additive"}, {"type": "constant_plans_only"},
                    {"type": "min_quality_margin", "limit": "sulfur_mgkg", "value": rng.choice([0.2, 1.0, 3.0])},
                    {"type": "max_outflow_utilization", "value": 0.7}, {"type": "require_not_fragile"}])]))
            if name == "rank_allowed":
                return respond(call(name))
            return respond(call(name, candidate_id=rng.choice(ids)) if name == "inspect_candidate"
                           else call(name, candidate_ids=rng.sample(ids, 2)))
        if pick < 0.7:
            return respond(content=rng.choice(["{", "ответ", '{"action": "select"}']))
        action = rng.choice(["select", "select", "keep_legacy", "refuse"])
        arguments = {"action": action, "reason_codes": ["random"], "summary": "s", "evidence_refs": ["context:legacy"]}
        if action == "select":
            arguments["candidate_id"] = rng.choice(ids_here)
        return respond(call("finalize", **arguments))

    return PolicyLLM(policy)


@pytest.fixture(scope="module")
def legacy():
    return {name: legacy_decide(name) for name in SCENARIOS}


@pytest.mark.parametrize("name", SCENARIOS)
def test_demo_policy_respects_invariants(name, legacy):
    check_invariants(name, legacy[name], agentic_decide(name, demo_llm()))


@pytest.mark.parametrize("name", SCENARIOS)
@pytest.mark.parametrize("seed", range(8))
def test_random_agent_behaviour_respects_invariants(name, seed, legacy):
    candidates = list(session_for(name).evaluations)[:40]
    decision = agentic_decide(name, random_policy(seed * 7919 + len(name), candidates))
    check_invariants(name, legacy[name], decision)


@pytest.mark.parametrize("name", SCENARIOS)
def test_provider_outage_reproduces_legacy(name, legacy):
    down = PolicyLLM(lambda role, messages, tools: (_ for _ in ()).throw(LLMError("network", "down")))
    decision = agentic_decide(name, down)
    assert decision["agentic"]["outcome"] == "fallback"
    check_invariants(name, legacy[name], decision)


def test_gate_refusal_is_never_turned_into_an_unchecked_plan(legacy):
    assert legacy["no_feasible"]["status"] == REFUSE
    for seed in range(6):
        decision = agentic_decide("no_feasible", random_policy(seed, ["hold", "c0001"]))
        if decision["status"] != REFUSE:
            assert fresh_gate_passes("no_feasible", decision)
