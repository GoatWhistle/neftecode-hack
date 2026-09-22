"""P2: блок choice — почему выбран вариант, почему не дешевле, что мешает при отказе."""

from neftecode.application.agentic import decision as decision_module
from neftecode.application.agentic.contracts import AgentConstraint
from neftecode.application.contracts import DataRejection
from neftecode.domain.advisory.entities import CheckResult, GateResult
from neftecode.domain.advisory.optimizer import Candidate, Evaluation
from neftecode.domain.shared.primitives import REFUSE
from neftecode.infrastructure.llm.scripted import ScriptedLLM

from _agentic_support import agentic_for, legacy_decide, maker_for, raw


OK = (CheckResult("quality.sulfur_mgkg", "pass", 9.0, 10.0, 0.0),)


def gate(plan_id: str, checks=OK) -> GateResult:
    return GateResult(plan_id, checks)


def cards(decision: dict) -> dict:
    return {card["candidate_id"]: card for card in decision["choice"]["candidates"]}


def categories(card: dict) -> set:
    return {reason["category"] for reason in card["reasons"]}


def test_cheaper_infeasible_is_excluded_with_gate_evidence_of_this_run():
    decision = legacy_decide("sour_crude")
    choice = decision["choice"]
    assert choice["decision_id"] == decision["decision_id"]
    assert choice["selected_id"] == decision["selected_plan"]["plan_id"]
    cheaper = cards(decision)[choice["cheaper_id"]]
    assert cheaper["cost_per_tonne"] < decision["cost_per_tonne"]
    admissible = {p["candidate_id"] for p in decision["tradeoff"]["points"]}
    if cheaper["verdict"] == "excluded":
        assert cheaper["candidate_id"] not in admissible
        assert cheaper["candidate_id"] != decision["selected_plan"]["plan_id"]
        gate = next(r for r in cheaper["reasons"] if r["category"] == "gate_fail")
        for ref in gate["evidence"]:
            assert ref["decision_id"] == decision["decision_id"]
            assert ref["candidate_id"] == cheaper["candidate_id"]
            assert ref["status"] == "fail"
            assert ref["observed"] is not None and ref["limit"] is not None
    hold = cards(decision)["hold"]
    assert hold["verdict"] == "excluded"
    refs = [ref for r in hold["reasons"] for ref in r.get("evidence", [])]
    assert refs and all(ref["constraint_id"] for ref in refs)


def test_policy_hold_names_min_useful_gain_not_a_tie_break():
    decision = legacy_decide("baseline")
    choice = decision["choice"]
    assert decision["status"] == "hold" and choice["selected_id"] == "hold"
    assert choice["determined_by"][0]["stage"] == "policy"
    overridden = choice["determined_by"][0]["candidate_ids"][0]
    card = cards(decision)[overridden]
    assert card["verdict"] == "admissible_not_selected"
    rule = card["reasons"][0]["rule"]
    assert rule["id"] == "min_useful_gain" and rule["observed"] < rule["value"]
    for other in choice["candidates"]:
        for reason in other["reasons"]:
            # выбор hold решён политикой, а не порядком идентификаторов относительно hold
            assert "с выбранным планом" not in reason["text"]
            if other["candidate_id"] != overridden:
                assert overridden in reason["text"]


def test_no_cheaper_option_is_said_explicitly():
    maker = maker_for(raw("baseline"))
    hold = Evaluation(Candidate("hold", {}, {"main": 1.0}, 100.0), gate("hold"), 300.0, 1.0, 0.1)
    worse = Evaluation(Candidate("c1", {}, {"main": 1.0}, 90.0, changes=1),
                       gate("c1"), 270.0, 1.2, 0.1)
    plan = type("Plan", (), {"plan_id": "hold"})()
    ranking = {"alternatives": [worse.to_dict()], "rejected": [], "reason": "rule", "ranking": ["-production_t"]}
    choice = maker._choice(status="hold", decision_id="d1", ranking=ranking, pool=[hold, worse],
                           examined=[hold, worse], plan=plan, evaluation=hold, lookahead=None, vetoed=(),
                           refusal=None)
    assert choice["cheaper_id"] is None and choice["cheaper_count"] == 0
    assert "дешевле выбранного нет" in choice["cheaper_note"]


def test_unknown_check_is_separate_from_violation_and_all_constraints_are_listed():
    maker = maker_for(raw("baseline"))
    checks = (
        CheckResult("quality.sulfur_mgkg", "fail", 11.0, 10.0, 1.0, "сера"),
        CheckResult("quality.sulfur_mgkg", "fail", 12.0, 10.0, 1.5, "сера"),
        CheckResult("outflow.main", "fail", 120.0, 100.0, 2.0, "отбор"),
        CheckResult("quality.cetane_number", "unknown", None, 51.0, 0.0, "нет данных"),
    )
    bad = Evaluation(Candidate("c9", {}, {"main": 1.0}, 90.0, changes=1), GateResult("c9", checks), 270.0, 0.9, 0.1)
    hold = Evaluation(Candidate("hold", {}, {"main": 1.0}, 100.0), gate("hold"), 300.0, 1.0, 0.1)
    plan = type("Plan", (), {"plan_id": "hold"})()
    choice = maker._choice(status="hold", decision_id="d1", ranking={"alternatives": [], "rejected": []},
                           pool=[hold], examined=[hold, bad], plan=plan, evaluation=hold, lookahead=None,
                           vetoed=(), refusal=None)
    card = next(c for c in choice["candidates"] if c["candidate_id"] == "c9")
    assert card["verdict"] == "excluded"
    assert categories(card) == {"gate_fail", "gate_unknown"}
    failed = next(r for r in card["reasons"] if r["category"] == "gate_fail")
    assert [e["constraint_id"] for e in failed["evidence"]] == ["quality.sulfur_mgkg", "outflow.main"]
    assert failed["evidence"][0]["points"] == 2 and failed["evidence"][0]["time_hours"] == 1.0
    assert failed["evidence_total"] == 2


def test_lookahead_switch_and_final_veto_are_named_as_their_stage():
    maker = maker_for(raw("baseline"))
    a = Evaluation(Candidate("a", {}, {"main": 1.0}, 100.0, changes=1), gate("a"), 300.0, 1.0, 0.1)
    b = Evaluation(Candidate("b", {}, {"main": 1.0}, 100.0, changes=1), gate("b"), 300.0, 1.1, 0.1)
    c = Evaluation(Candidate("c", {}, {"main": 1.0}, 100.0, changes=1), gate("c"), 300.0, 1.2, 0.1)
    lookahead = {"switched": True, "initial_plan": "a", "min_reaction_hours": 6.0,
                 "initial": {"constraint": "quality.sulfur_mgkg", "hours_to_violation": 3.0,
                             "observed": 10.4, "limit": 10.0}}
    vetoed = ({"candidate_id": "b", "reason": {"category": "final_veto", "stage": "robustness", "text": "t",
                                               "rule": {"id": "mandatory_robustness"}}},)
    plan = type("Plan", (), {"plan_id": "c"})()
    choice = maker._choice(status="recommend_scenario", decision_id="d1", ranking={"alternatives": []},
                           pool=[a, c], examined=[a, b, c], plan=plan, evaluation=c, lookahead=lookahead,
                           vetoed=vetoed, refusal=None)
    stages = [d["stage"] for d in choice["determined_by"]]
    assert stages == ["final_veto", "lookahead"]
    by = {card["candidate_id"]: card for card in choice["candidates"]}
    assert categories(by["a"]) == {"lookahead"}
    assert by["a"]["reasons"][0]["evidence"][0]["decision_id"] == "d1"
    assert categories(by["b"]) == {"final_veto"}
    assert by["a"]["verdict"] == by["b"]["verdict"] == "excluded"


def test_no_feasible_refusal_lists_candidates_and_is_domain_proven():
    decision = legacy_decide("no_feasible")
    choice = decision["choice"]
    assert decision["status"] == REFUSE and choice["selected_id"] is None
    assert choice["refusal"]["domain_impossibility_proven"] is True
    assert choice["refusal"]["agents_skipped"] is False
    assert choice["candidates"] and all(card["verdict"] == "excluded" for card in choice["candidates"])


def test_data_refusal_skips_agents_and_lists_no_candidates():
    maker = agentic_for("baseline", ScriptedLLM([]))
    decision = maker.decide(budget=400, raw_scenario=raw("baseline"),
                            data_rejection=DataRejection("нет лаборатории", ("лабораторный анализ серы",)))
    assert decision["agentic"]["outcome"] == "skipped"
    assert decision["choice"]["refusal"] == {"kind": "data", "stage": "data", "agents_skipped": True,
                                             "domain_impossibility_proven": False}
    assert decision["choice"]["candidates"] == []


def test_agent_veto_of_core_choice_is_shown_as_the_deciding_stage():
    class VetoHold:
        def run(self, *, session, **kwargs):
            session.veto(["hold"], "quality")
            return type("Run", (), {"opinions": [], "final": decision_module.OrchestratorFinal(
                action="keep_legacy", candidate_id=None, reason_codes=("x",), summary="s", evidence_refs=())})()

    maker = agentic_for("baseline", ScriptedLLM([]))
    maker.orchestrator = VetoHold()
    decision = maker.decide(budget=400, raw_scenario=raw("baseline"))
    choice = decision["choice"]
    assert decision["selected_plan"]["plan_id"] != "hold"
    assert choice["selected_id"] == decision["selected_plan"]["plan_id"]
    assert choice["agents"]["legacy_excluded"] is True and choice["agents"]["legacy_plan_id"] == "hold"
    assert choice["determined_by"][0]["stage"] == "agents"
    hold = cards(decision)["hold"]
    assert hold["verdict"] == "excluded" and "agent_veto" in categories(hold)
    assert choice["decision_id"] == decision["decision_id"]


def test_agent_constraint_exclusion_is_not_called_a_gate_violation():
    class Tighten:
        def run(self, *, session, **kwargs):
            session.add_constraints([AgentConstraint("max_changes", None, 0)])
            return type("Run", (), {"opinions": [], "final": decision_module.OrchestratorFinal(
                action="keep_legacy", candidate_id=None, reason_codes=("x",), summary="s", evidence_refs=())})()

    maker = agentic_for("sour_crude", ScriptedLLM([]))
    maker.orchestrator = Tighten()
    decision = maker.decide(budget=400, raw_scenario=raw("sour_crude"))
    choice = decision["choice"]
    constrained = [card for card in choice["candidates"] if "agent_constraint" in categories(card)]
    for card in constrained:
        assert "gate_fail" not in categories(card)
        rule = next(r for r in card["reasons"] if r["category"] == "agent_constraint")["rule"]
        assert rule["constraints"][0]["type"] == "max_changes"
    if decision["status"] == REFUSE:
        assert choice["refusal"]["stage"] in ("agents", "search", "final_recheck", "final_veto")


def test_viewing_choice_does_not_change_the_decision():
    decision = legacy_decide("sour_crude")
    again = legacy_decide("sour_crude")
    assert decision["decision_id"] == again["decision_id"]
    assert decision["choice"] == again["choice"]
