import json
from pathlib import Path

from neftecode.application.agentic.budget import AgentBudget
from neftecode.application.agentic.contracts import AgentSettings
from neftecode.application.agentic.session import DecisionSession
from neftecode.application.use_cases.make_decision import MakeDecision
from neftecode.evaluation.robustness import RobustnessCheck
from neftecode.infrastructure.config.scenario import parse_scenario
from neftecode.infrastructure.response.unavailable import UnavailableResponseEffect

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = ROOT / "config" / "scenarios"
BUDGET = 400


def raw(name: str) -> dict:
    return json.loads((SCENARIOS / f"{name}.json").read_text(encoding="utf-8"))


def maker_for(document: dict) -> MakeDecision:
    scenario = parse_scenario(document)
    return MakeDecision(scenario, robustness_evaluator=RobustnessCheck(scenario, document,
                                                                       scenario_parser=parse_scenario))


def session_for(name: str, settings: AgentSettings | None = None, document: dict | None = None,
                **overrides) -> DecisionSession:
    document = document or raw(name)
    maker = maker_for(document)
    legacy = maker.decide(budget=BUDGET, raw_scenario=document)
    outcome = maker._search(BUDGET)
    settings = settings or AgentSettings()
    return DecisionSession(maker, outcome, legacy, settings, AgentBudget(settings), evaluation_budget=BUDGET,
                           raw_scenario=document, response_effect=UnavailableResponseEffect(), **overrides)


def agentic_for(name: str, llm, settings: AgentSettings | None = None, document: dict | None = None):
    from neftecode.application.agentic.decision import AgenticMakeDecision

    document = document or raw(name)
    scenario = parse_scenario(document)
    return AgenticMakeDecision(scenario, llm, settings=settings or AgentSettings(),
                               robustness_evaluator=RobustnessCheck(scenario, document, scenario_parser=parse_scenario),
                               response_effect=UnavailableResponseEffect())


def agentic_decide(name: str, llm, settings: AgentSettings | None = None, **kwargs) -> dict:
    document = raw(name)
    return agentic_for(name, llm, settings, document).decide(budget=BUDGET, raw_scenario=document, **kwargs)


def legacy_decide(name: str, **kwargs) -> dict:
    document = raw(name)
    return maker_for(document).decide(budget=BUDGET, raw_scenario=document, **kwargs)


def without_agentic(decision: dict) -> dict:
    return {k: v for k, v in decision.items() if k != "agentic"}
