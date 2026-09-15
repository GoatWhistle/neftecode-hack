"""Model answers become machine decisions only through strict parsers."""
import json
import math

import pytest

from neftecode.application.agentic.budget import AgentBudget, BudgetExhausted
from neftecode.application.agentic.contracts import (AgentConstraint, AgentSettings, AgentTraceEvent,
                                                      ContractViolation, Opinion, compact, extract_json_object,
                                                      parse_constraint, parse_constraints, parse_final, parse_opinion)

CANDIDATES = ("hold", "c0025")
EVIDENCE = ("get_quality_margins:c0025", "context:shortlist")


def opinion(**overrides):
    base = {"verdict": "ACCEPT", "risk_level": "low",
            "reasons": [{"code": "margin_ok", "text": "Запас по сере 1.2 мг/кг", "candidate_id": "c0025"}],
            "confidence": 0.7, "evidence_refs": ["get_quality_margins:c0025"]}
    base.update(overrides)
    return base


# --- constraints ---

@pytest.mark.parametrize("raw, expected", [
    ({"type": "min_quality_margin", "limit": "sulfur_mgkg", "value": 0.5},
     AgentConstraint("min_quality_margin", "sulfur_mgkg", 0.5)),
    ({"type": "max_changes", "value": 1}, AgentConstraint("max_changes", None, 1)),
    ({"type": "forbid_additive"}, AgentConstraint("forbid_additive")),
    ({"type": "max_outflow_utilization", "value": 0.8}, AgentConstraint("max_outflow_utilization", None, 0.8)),
    ({"type": "constant_plans_only"}, AgentConstraint("constant_plans_only")),
    ({"type": "min_hours_to_violation", "value": 12}, AgentConstraint("min_hours_to_violation", None, 12.0)),
    ({"type": "require_not_fragile"}, AgentConstraint("require_not_fragile")),
])
def test_valid_constraints_parse(raw, expected):
    assert parse_constraint(raw) == expected
    assert parse_constraint(json.dumps(raw)) == expected


@pytest.mark.parametrize("raw", [
    {"type": "raise_sulfur_limit", "value": 12},                               # not in the vocabulary
    {"type": "min_quality_margin", "limit": "sulfur_mgkg", "value": -1.0},      # would loosen the limit
    {"type": "min_quality_margin", "limit": "sulfur_mgkg", "value": 50},        # out of range
    {"type": "min_quality_margin", "limit": "color", "value": 1},               # unknown limit
    {"type": "min_quality_margin", "value": 1},                                 # limit missing
    {"type": "max_changes", "value": 3},
    {"type": "max_changes", "value": 1.5},
    {"type": "max_changes", "value": True},
    {"type": "max_outflow_utilization", "value": 1.5},
    {"type": "max_outflow_utilization", "value": math.nan},
    {"type": "forbid_additive", "value": 1},
    {"type": "max_changes", "limit": "sulfur_mgkg", "value": 1},
    {"type": "max_changes", "value": 1, "note": "extra"},
    "not json",
    ["forbid_additive"],
])
def test_invalid_constraints_are_rejected(raw):
    with pytest.raises(ContractViolation):
        parse_constraint(raw)


def test_constraints_are_accepted_one_by_one_and_deduplicated():
    accepted, rejected = parse_constraints([
        {"type": "forbid_additive"}, {"type": "forbid_additive"}, {"type": "max_changes", "value": 9},
        {"type": "constant_plans_only"}, {"type": "max_changes", "value": 1}, {"type": "require_not_fragile"}])
    assert [c.type for c in accepted] == ["forbid_additive", "constant_plans_only"]
    assert len(rejected) == 3  # out of range, fifth and sixth beyond the limit of four


# --- opinions ---

def test_valid_opinion_parses():
    parsed = parse_opinion("quality", opinion(candidate_verdicts={"c0025": "ACCEPT", "ghost": "REJECT"},
                                             preferred_candidates=["c0025", "ghost"],
                                             proposed_constraints=[{"type": "min_quality_margin",
                                                                    "limit": "sulfur_mgkg", "value": 0.5},
                                                                   {"type": "bad"}]),
                           candidates=CANDIDATES, evidence=EVIDENCE)
    assert parsed.verdict == "ACCEPT" and parsed.valid
    assert parsed.candidate_verdicts == {"c0025": "ACCEPT"}
    assert parsed.preferred_candidates == ("c0025",)
    assert parsed.proposed_constraints == (AgentConstraint("min_quality_margin", "sulfur_mgkg", 0.5),)
    assert len(parsed.rejected_constraints) == 1
    assert parsed.to_dict()["role"] == "quality"


@pytest.mark.parametrize("change", [
    {"verdict": "OK"}, {"risk_level": "severe"}, {"confidence": 1.5}, {"confidence": True},
    {"confidence": math.inf}, {"reasons": []}, {"reasons": "text"},
    {"reasons": [{"code": "Bad Code", "text": "x"}]}, {"reasons": [{"code": "ok"}]},
    {"candidate_verdicts": {"c0025": "MAYBE"}}, {"candidate_verdicts": ["c0025"]}, {"unexpected": 1},
])
def test_invalid_opinions_are_rejected(change):
    with pytest.raises(ContractViolation):
        parse_opinion("reliability", opinion(**change), candidates=CANDIDATES, evidence=EVIDENCE)


def test_missing_required_field_is_rejected():
    raw = opinion()
    del raw["confidence"]
    with pytest.raises(ContractViolation):
        parse_opinion("quality", raw, candidates=CANDIDATES, evidence=EVIDENCE)


def test_ungrounded_commitment_is_downgraded_to_unknown():
    parsed = parse_opinion("quality", opinion(verdict="REJECT", risk_level="high", evidence_refs=["invented:1"],
                                             candidate_verdicts={"c0025": "REJECT"}),
                           candidates=CANDIDATES, evidence=EVIDENCE)
    assert parsed.verdict == "UNKNOWN" and parsed.risk_level == "unknown"
    assert parsed.vetoed == ()
    assert parsed.reasons[-1].code == "ungrounded_verdict"


def test_top_level_reject_without_per_candidate_verdicts_vetoes_all_asked():
    parsed = parse_opinion("quality", opinion(verdict="REJECT", risk_level="high"),
                           candidates=CANDIDATES, evidence=EVIDENCE)
    assert parsed.vetoed == ("c0025", "hold")


def test_long_text_is_truncated_not_trusted():
    parsed = parse_opinion("quality", opinion(reasons=[{"code": "x", "text": "a" * 5000}]),
                           candidates=CANDIDATES, evidence=EVIDENCE)
    assert len(parsed.reasons[0].text) == 300


def test_unknown_opinion_is_marked_invalid():
    unknown = Opinion.unknown("quality", "llm_error_timeout", "timeout")
    assert unknown.verdict == "UNKNOWN" and unknown.valid is False and unknown.vetoed == ()


# --- orchestrator final ---

def test_valid_finals_parse():
    final = parse_final({"action": "select", "candidate_id": "c0025", "reason_codes": ["best_allowed"],
                         "summary": "План проходит проверки", "evidence_refs": ["context:shortlist", "x:y"]},
                        evidence=EVIDENCE)
    assert final.candidate_id == "c0025" and final.evidence_refs == ("context:shortlist",)
    keep = parse_final({"action": "keep_legacy", "candidate_id": "c0025", "reason_codes": ["legacy_ok"],
                        "summary": "ok"}, evidence=EVIDENCE)
    assert keep.candidate_id is None


@pytest.mark.parametrize("raw", [
    {"action": "approve", "reason_codes": ["x"], "summary": "s"},
    {"action": "select", "reason_codes": ["x"], "summary": "s"},
    {"action": "select", "candidate_id": "c 1; drop", "reason_codes": ["x"], "summary": "s"},
    {"action": "refuse", "reason_codes": [], "summary": "s"},
    {"action": "refuse", "reason_codes": ["UPPER"], "summary": "s"},
    {"action": "refuse", "reason_codes": ["x"]},
    {"action": "refuse", "reason_codes": ["x"], "summary": "s", "plan": {"steps": []}},
])
def test_invalid_finals_are_rejected(raw):
    with pytest.raises(ContractViolation):
        parse_final(raw, evidence=EVIDENCE)


# --- repair ---

@pytest.mark.parametrize("text, expected", [
    ('{"a": 1}', {"a": 1}),
    ('```json\n{"a": 1}\n```', {"a": 1}),
    ('Вот ответ: {"a": {"b": 2}} конец', {"a": {"b": 2}}),
    ('{"a": 1} {"b": 2}', None),
    ('{"a": 1', None),
    ("[1, 2]", None),
    ("", None),
])
def test_local_repair_accepts_only_a_single_object(text, expected):
    assert extract_json_object(text) == expected


# --- settings, trace, budget ---

def test_settings_validate():
    assert AgentSettings().max_llm_calls == 12
    with pytest.raises(ValueError):
        AgentSettings(max_llm_calls=0)
    with pytest.raises(ValueError):
        AgentSettings(max_steps=1)
    assert AgentSettings.from_mapping({"max_steps": 3, "unknown": 1}).max_steps == 3


def test_trace_event_is_compact():
    event = AgentTraceEvent(1, "quality", 2, "tool", tool_name="get_quality_margins",
                            tool_input_summary=compact({"candidate_id": "c0025"}, 200), candidate_ids=("c0025",))
    assert event.to_dict() == {"seq": 1, "agent": "quality", "step": 2, "kind": "tool",
                               "tool_name": "get_quality_margins", "tool_input_summary": '{"candidate_id":"c0025"}',
                               "candidate_ids": ["c0025"]}
    assert compact({"x": "a" * 100}, 20).endswith("…") and len(compact({"x": "a" * 100}, 20)) == 20


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_budget_bounds_calls_and_time():
    clock = Clock()
    budget = AgentBudget(AgentSettings(max_llm_calls=2, timeout_s=10), clock=clock)
    budget.take_call("orchestrator")
    budget.take_call("quality")
    with pytest.raises(BudgetExhausted) as calls:
        budget.take_call("quality")
    assert calls.value.what == "llm_calls"
    late = AgentBudget(AgentSettings(timeout_s=10), clock=clock)
    clock.now = 10.0
    with pytest.raises(BudgetExhausted) as timeout:
        late.take_call("orchestrator")
    assert timeout.value.what == "timeout"


def test_budget_bounds_replans_consults_and_robustness():
    budget = AgentBudget(AgentSettings(max_replans=1, max_specialist_consults=1, max_robustness_runs=1))
    assert budget.take_replan() and not budget.take_replan()
    assert budget.take_consult("quality") and not budget.take_consult("quality")
    assert budget.take_consult("reliability")
    assert budget.take_robustness() and not budget.take_robustness()
    budget.add_usage({"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15, "bogus": 3})
    assert budget.to_dict()["usage"] == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
