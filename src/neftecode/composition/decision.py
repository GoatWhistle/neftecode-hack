"""Composition of the interactive decision flow."""
from pathlib import Path

from neftecode.application.services.explain import explain
from neftecode.application.services.trust import DataTrustAgent
from neftecode.application.use_cases.make_decision import MakeDecision
from neftecode.domain.production.inventory import initial_state
from neftecode.evaluation.robustness import RobustnessCheck
from neftecode.infrastructure.config.scenario import ScenarioError, parse_scenario
from neftecode.presentation.demo import Demo
from neftecode.presentation.web.server import DemoService
from neftecode.presentation.web.ui import Screen, error_payload

def run_demo_decision(raw: dict, state: dict, budget: int,
                      trust_cfg: dict | None = None) -> dict:
    """Compose the interactive demo with the real parser, core and robustness check."""
    try:
        scenario = parse_scenario(raw)
    except ScenarioError as exc:
        return {"ok": False, "rejected": True, "reason": str(exc),
                "screen": error_payload(str(exc))}
    decision = MakeDecision(
        scenario, robustness_evaluator=RobustnessCheck(
            scenario, raw, scenario_parser=parse_scenario
        )
    ).decide(state=state, budget=budget, trust_cfg=trust_cfg, raw_scenario=raw)
    trust = DataTrustAgent(trust_cfg or {}).assess(state)
    screen = Screen(
        decision,
        explain(decision, scenario),
        inventories={key: value.inventory_t for key, value in initial_state(scenario).items()},
        sources=[source.to_dict() for source in trust.sources.values()],
    ).payload()
    return {"ok": True, "rejected": False, "scenario_id": scenario.scenario_id,
            "decision": decision, "screen": screen}

def make_interactive_demo(raw: dict, budget: int = 400) -> Demo:
    return Demo(raw, run_demo_decision, budget)

def make_demo_service(root: Path, budget: int = 400) -> DemoService:
    return DemoService(Path(root), make_interactive_demo, budget)
