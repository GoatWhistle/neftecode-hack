"""Explanations bound to the calculation, and refusals that say what would change the answer."""
from pathlib import Path

import pytest

from neftecode.application.services.explain import (BAD_DATA, LAB_DELAY_HOURS, MODEL_NOT_APPLICABLE, NO_FEASIBLE_PLAN,
                               Evidence, ExplanationError, Statement, explain, explain_decision,
                               explain_refusal)
from neftecode.application.use_cases.make_decision import MakeDecision
from neftecode.infrastructure.config.scenario import load_scenario

BASELINE = Path("config/scenarios/baseline.json")
SOUR = Path("config/scenarios/sour_crude.json")
NO_FEASIBLE = Path("config/scenarios/no_feasible.json")
BUDGET = 400


def decide(path):
    scenario = load_scenario(path)
    return MakeDecision(scenario).decide(budget=BUDGET), scenario


def healthy_state():
    return {"decision_time": "2026-01-05T08:00:00",
            "lab_value": 8.0, "lab_age_hours": 5.0, "lab_usable": True,
            "pak_value": 8.4, "pak_age_minutes": 10.0, "pak_usable": True,
            "pak_frozen": False, "pak_conflict": False, "telemetry_missing_fraction": 0.0}


# --- A statement cannot drift from the number it talks about ---

def test_a_statement_without_evidence_is_refused():
    with pytest.raises(ExplanationError, match="без ссылки запрещено"):
        Statement("x", "что-то произошло", 1.0, ())


def test_a_number_not_matching_any_citation_is_refused():
    citation = Evidence("gate_check", "quality.sulfur_mgkg", 8.0)
    with pytest.raises(ExplanationError, match="не совпадает ни с одной ссылкой"):
        Statement("sulfur", "сера 9.5", 9.5, (citation,))


def test_a_matching_number_is_accepted():
    citation = Evidence("gate_check", "quality.sulfur_mgkg", 8.0)
    assert Statement("sulfur", "сера 8.0", 8.0, (citation,)).value == 8.0


def test_an_empty_citation_is_refused():
    with pytest.raises(ExplanationError, match="пуста"):
        Evidence("gate_check", "quality.sulfur_mgkg")


def test_an_unnamed_source_is_refused():
    with pytest.raises(ExplanationError, match="называть источник"):
        Evidence("gate_check", "   ", 1.0)


def test_an_unknown_evidence_kind_is_refused():
    with pytest.raises(ExplanationError, match="Неизвестный вид"):
        Evidence("интуиция", "что-то", 1.0)


def test_a_statement_without_a_number_still_needs_a_citation():
    citation = Evidence("gate_check", "quality.cetane_number", None, "неизвестно")
    assert Statement("cetane", "цетан неизвестен", None, (citation,)).value is None


# --- Explaining a plan ---

def test_every_number_in_the_explanation_comes_from_the_calculation():
    decision, scenario = decide(SOUR)
    explanation = explain_decision(decision, scenario)
    for statement in explanation["statements"]:
        if statement["value"] is None:
            continue
        values = [e["value"] for e in statement["evidence"] if e["value"] is not None]
        assert any(abs(v - statement["value"]) < 1e-6 for v in values)


def test_the_quality_numbers_match_the_gate_verdicts():
    """The explanation reports the tightest point of the plan, taken from the gate itself."""
    decision, scenario = decide(SOUR)
    explanation = explain_decision(decision, scenario)
    own = [c for c in decision["gate"]["checks"]
           if c["constraint_id"] == "quality.sulfur_mgkg" and c["observed"] is not None]
    tightest = min(own, key=lambda c: abs(c["limit"] - c["observed"]))
    sulfur = next(s for s in explanation["statements"] if s["topic"] == "sulfur_mgkg")
    assert sulfur["value"] == pytest.approx(tightest["observed"])
    assert sulfur["value"] == max(c["observed"] for c in own), "показана не худшая точка"


def test_the_explanation_reports_cause_action_effect_and_limits():
    decision, scenario = decide(SOUR)
    explanation = explain_decision(decision, scenario)
    topics = {s["topic"] for s in explanation["statements"]}
    assert "sulfur_mgkg" in topics, "нет проверенного показателя качества"
    assert any(t.startswith("control.") for t in topics), "нет предлагаемого действия"
    assert "production" in topics and "cost" in topics, "нет ожидаемого эффекта"
    assert explanation["checks_total"] > 0


def test_the_declared_response_delay_is_stated():
    decision, scenario = decide(SOUR)
    explanation = explain_decision(decision, scenario)
    delay = next(s for s in explanation["statements"] if s["topic"] == "delay")
    assert delay["value"] == scenario.stages["hydrotreating"].response_lag_hours.value


def test_alternatives_are_shown_with_why_they_lost():
    decision, scenario = decide(SOUR)
    explanation = explain_decision(decision, scenario)
    assert explanation["alternatives"]
    assert all("правилу сравнения" in a["why_not"] for a in explanation["alternatives"])


def test_no_unverified_process_cause_can_be_asserted():
    """Nothing here explains why the plant behaves as it does, only what was computed."""
    decision, scenario = decide(SOUR)
    explanation = explain_decision(decision, scenario)
    assert any("не причину поведения установки" in limit for limit in explanation["limits"])
    kinds = {e["kind"] for s in explanation["statements"] for e in s["evidence"]}
    assert kinds <= {"observation", "scenario", "model", "gate_check", "policy"}


def test_the_severity_statement_denies_being_about_equipment_life():
    decision, scenario = decide(SOUR)
    explanation = explain_decision(decision, scenario)
    severity = [s for s in explanation["statements"] if s["topic"] == "severity"]
    if severity:
        assert any("не вероятность отказа" in e["detail"] for e in severity[0]["evidence"])


def test_an_unknown_quality_is_explained_as_unknown():
    decision, scenario = decide(BASELINE)
    explanation = explain_decision(decision, scenario)
    for statement in explanation["statements"]:
        if statement["value"] is None and statement["topic"] in ("t95_c", "cetane_number"):
            assert "неизвестно" in statement["text"]


# --- Refusals ---

def test_a_data_refusal_asks_for_a_measurement_and_states_its_delay():
    scenario = load_scenario(BASELINE)
    state = dict(healthy_state(), lab_value=None, lab_usable=False,
                 pak_frozen=True, pak_usable=False)
    decision = MakeDecision(scenario).decide(state=state, budget=BUDGET)
    explanation = explain_refusal(decision, scenario)
    assert explanation["kind"] == BAD_DATA
    lab = [s for s in explanation["next_steps"] if "лабораторный" in s["need"]]
    assert lab, "отказ по данным обязан назвать нужное измерение"
    assert lab[0]["available_in_hours"] == LAB_DELAY_HOURS
    assert "не успеть" in lab[0]["caveat"]


def test_a_plan_refusal_names_the_missing_resource():
    decision, scenario = decide(NO_FEASIBLE)
    explanation = explain_refusal(decision, scenario)
    assert explanation["kind"] == NO_FEASIBLE_PLAN
    assert explanation["next_steps"]
    assert all(step["kind"] == "resource_or_scenario_condition"
               for step in explanation["next_steps"])


def test_the_three_refusal_kinds_stay_distinct():
    scenario = load_scenario(BASELINE)
    data_refusal = explain_refusal({"status": "refuse", "refusal": {"kind": "data", "missing": ["x"]}},
                                   scenario)
    plan_refusal = explain_refusal({"status": "refuse", "refusal": {"kind": "no_feasible_plan"}},
                                   scenario)
    model_refusal = explain_refusal(
        {"status": "refuse", "refusal": {"kind": MODEL_NOT_APPLICABLE}}, scenario)
    kinds = {data_refusal["kind"], plan_refusal["kind"], model_refusal["kind"]}
    assert kinds == {BAD_DATA, NO_FEASIBLE_PLAN, MODEL_NOT_APPLICABLE}


def test_a_model_refusal_asks_for_a_regime_not_a_measurement():
    scenario = load_scenario(BASELINE)
    explanation = explain_refusal(
        {"status": "refuse", "refusal": {"kind": MODEL_NOT_APPLICABLE}}, scenario)
    assert explanation["next_steps"][0]["kind"] == "regime"


def test_a_refusal_never_offers_to_relax_a_hard_limit():
    decision, scenario = decide(NO_FEASIBLE)
    explanation = explain_refusal(decision, scenario)
    assert any("не снимается ослаблением" in limit for limit in explanation["limits"])
    assert any("10 мг/кг" in limit for limit in explanation["limits"])


def test_a_refusal_says_it_is_not_the_absence_of_risk():
    decision, scenario = decide(NO_FEASIBLE)
    assert any("не отсутствие риска" in limit
               for limit in explain_refusal(decision, scenario)["limits"])


def test_a_refusal_always_offers_at_least_one_next_step():
    scenario = load_scenario(BASELINE)
    for refusal in ({"kind": "data"}, {"kind": "no_feasible_plan"}, {}):
        explanation = explain_refusal({"status": "refuse", "refusal": refusal}, scenario)
        assert explanation["next_steps"], "отказ без следующего шага бесполезен"


# --- Dispatch ---

def test_dispatch_picks_the_right_explanation():
    plan_decision, scenario = decide(SOUR)
    assert "statements" in explain(plan_decision, scenario)
    refusal_decision, refusal_scenario = decide(NO_FEASIBLE)
    assert "next_steps" in explain(refusal_decision, refusal_scenario)


def test_explanations_are_reproducible():
    decision, scenario = decide(SOUR)
    assert explain(decision, scenario) == explain(decision, scenario)
