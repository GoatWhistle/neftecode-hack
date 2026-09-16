"""Composition of the interactive decision flow."""
from pathlib import Path

from neftecode.application.services.explain import explain
from neftecode.application.services.trust import DataTrustAgent
from neftecode.domain.production.inventory import initial_state
from neftecode.evaluation.robustness import RobustnessCheck
from neftecode.infrastructure.agentic import default_decision_factory
from neftecode.infrastructure.config.scenario import ScenarioError, parse_scenario
from neftecode.infrastructure.config.trust_rules import load_trust_rules
from neftecode.presentation.demo import Demo
from neftecode.presentation.web.server import DemoService
from neftecode.presentation.web.ui import Screen, error_payload

def run_demo_decision(raw: dict, state: dict, budget: int, trust_cfg: dict,
                      decision_factory=None, trust_origin: str | None = None) -> dict:
    """Compose the interactive demo with the real parser, core and robustness check.

    `trust_cfg` обязателен: пороги доверия к источникам приходят снаружи (load_trust_rules или
    model.pkl), пустой конфиг здесь не подставляется.
    """
    if not isinstance(trust_cfg, dict):
        raise ValueError("trust_cfg должен быть словарём порогов доверия к источникам")
    try:
        scenario = parse_scenario(raw)
    except ScenarioError as exc:
        return {"ok": False, "rejected": True, "reason": str(exc),
                "screen": error_payload(str(exc))}
    factory = decision_factory or default_decision_factory()
    decision = factory(
        scenario, RobustnessCheck(scenario, raw, scenario_parser=parse_scenario)
    ).decide(state=state, budget=budget, trust_cfg=trust_cfg, raw_scenario=raw)
    trust = DataTrustAgent(trust_cfg).assess(state)
    screen = Screen(
        decision,
        explain(decision, scenario),
        inventories={key: value.inventory_t for key, value in initial_state(scenario).items()},
        sources=[source.to_dict() for source in trust.sources.values()],
        rule_origin=trust_origin,
    ).payload()
    return {"ok": True, "rejected": False, "scenario_id": scenario.scenario_id,
            "decision": decision, "screen": screen, "trust_origin": trust_origin}

def make_interactive_demo(raw: dict, budget: int, trust_cfg: dict, trust_origin: str | None = None) -> Demo:
    return Demo(raw, run_demo_decision, trust_cfg, budget, trust_origin=trust_origin)

def make_demo_service(root: Path, budget: int = 400) -> DemoService:
    root = Path(root)
    trust_cfg, trust_origin = load_trust_rules(root, root / "artifacts")
    return DemoService(root, lambda raw, budget: make_interactive_demo(raw, budget, trust_cfg, trust_origin),
                       budget)
