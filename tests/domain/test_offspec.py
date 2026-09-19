import json
from pathlib import Path

import pytest

from neftecode.application.use_cases.make_decision import MakeDecision
from neftecode.domain.production.offspec import OFFSPEC_SHARE_KEY, offspec_block
from neftecode.infrastructure.config.scenario import ScenarioError, parse_scenario

SCENARIOS = Path("config/scenarios")


def raw(name):
    return json.loads((SCENARIOS / f"{name}.json").read_text(encoding="utf-8"))


def decide(name):
    document = raw(name)
    return MakeDecision(parse_scenario(document)).decide(budget=300, raw_scenario=document)


@pytest.mark.parametrize("name", sorted(p.stem for p in SCENARIOS.glob("*.json")))
def test_every_scenario_declares_the_given_share(name):
    economics = raw(name)["economics"][OFFSPEC_SHARE_KEY]
    assert economics["value"] == 0.05
    assert economics["source"] == "given"
    assert economics["unit"] == "доля"


def test_block_uses_the_declared_share_price_and_stock():
    scenario = parse_scenario(raw("baseline"))
    block = offspec_block(scenario, 1.0, 1.2, 500.0)
    main = scenario.available_tanks()[0]
    assert block["rework_cost"] == pytest.approx(0.05 * main.cost_per_t.value * main.inventory.value)
    assert block["delta_cost_per_tonne"] == pytest.approx(0.2)
    assert block["plan_extra_cost"] == pytest.approx(100.0)


def test_block_never_claims_to_decide_admissibility():
    block = offspec_block(parse_scenario(raw("baseline")), 1.0, 1.0, 300.0)
    assert block["affects_admissibility"] is False


def test_missing_share_is_stated_not_guessed():
    document = raw("baseline")
    scenario = parse_scenario(document)
    stripped = {k: v for k, v in scenario.economics.items() if k != OFFSPEC_SHARE_KEY}
    block = offspec_block(type(scenario)(**{**scenario.__dict__, "economics": stripped}),
                          1.0, 1.2, 300.0)
    assert block["available"] is False
    assert OFFSPEC_SHARE_KEY in block["reason"]


def test_scenario_without_the_share_is_rejected_by_the_loader():
    document = raw("baseline")
    del document["economics"][OFFSPEC_SHARE_KEY]
    with pytest.raises(ScenarioError):
        parse_scenario(document)


@pytest.mark.parametrize("name", ["baseline", "sour_crude", "ample_reserve"])
def test_decision_reports_both_figures(name):
    decision = decide(name)
    block = decision["lookahead"]["offspec"]
    assert block["available"] is True
    assert block["rework_cost"] == pytest.approx(200.0)
    assert block["plan_extra_cost"] is not None


def test_money_does_not_change_the_chosen_plan():
    document = raw("sour_crude")
    before = MakeDecision(parse_scenario(document)).decide(budget=300, raw_scenario=document)
    document["economics"][OFFSPEC_SHARE_KEY]["value"] = 0.5
    after = MakeDecision(parse_scenario(document)).decide(budget=300, raw_scenario=document)
    assert before["status"] == after["status"]
    assert before["selected_plan"]["plan_id"] == after["selected_plan"]["plan_id"]
    assert before["production_t"] == after["production_t"]
    assert before["cost_per_tonne"] == after["cost_per_tonne"]
    assert after["lookahead"]["offspec"]["rework_cost"] == pytest.approx(2000.0)


def test_refusal_carries_no_money_block():
    decision = decide("no_feasible")
    assert decision["status"] == "refuse"
    assert (decision["lookahead"] or {}).get("offspec") is None
