"""Composition of the interactive decision flow."""
from pathlib import Path

from neftecode.application.ports.live import ForecastBindingError
from neftecode.application.services.explain import explain
from neftecode.application.services.trust import DataTrustAgent
from neftecode.application.use_cases.get_live_advice import binding_summary, decision_context
from neftecode.domain.production.inventory import initial_state
from neftecode.evaluation.robustness import RobustnessCheck
from neftecode.infrastructure.agentic import default_decision_factory
from neftecode.infrastructure.config.scenario import ScenarioError, parse_scenario
from neftecode.infrastructure.config.trust_rules import load_trust_rules
from neftecode.infrastructure.live.advisor import load_response_model
from neftecode.infrastructure.live.snapshots import bind_snapshot, load_snapshots
from neftecode.presentation.demo import Demo, state_origin_label
from neftecode.presentation.web.server import DemoService
from neftecode.presentation.web.ui import Screen, error_payload

def run_demo_decision(raw: dict, state: dict, budget: int, trust_cfg: dict,
                      decision_factory=None, trust_origin: str | None = None,
                      snapshot: dict | None = None, response_model: dict | None = None) -> dict:
    """Compose the interactive demo with the real parser, core and robustness check.

    `trust_cfg` обязателен: пороги доверия к источникам приходят снаружи (load_trust_rules или
    model.pkl), пустой конфиг здесь не подставляется. Со срезом (`snapshot`, C3) сценарий проходит
    через тот же связыватель, что и `advise`: прогноз, измеренные уставки, приток и окно резервуара.
    """
    if not isinstance(trust_cfg, dict):
        raise ValueError("trust_cfg должен быть словарём порогов доверия к источникам")
    try:
        scenario = parse_scenario(raw)
        if snapshot is not None:
            scenario, raw = bind_snapshot(raw, state, snapshot, response_model, trust_cfg)
    except (ScenarioError, ForecastBindingError) as exc:
        return {"ok": False, "rejected": True, "reason": str(exc),
                "screen": error_payload(str(exc))}
    factory = decision_factory or default_decision_factory()
    evaluator = RobustnessCheck(scenario, raw, scenario_parser=parse_scenario)
    # Реальный срез: агенты видят тот же живой контекст, что в advise (прогноз, измерения, отклик).
    maker = (factory(scenario, evaluator) if snapshot is None else
             factory(scenario, evaluator, decision_context(snapshot.get("at"), snapshot.get("forecast"), raw)))
    decision = maker.decide(state=state, budget=budget, trust_cfg=trust_cfg, raw_scenario=raw)
    trust = DataTrustAgent(trust_cfg).assess(state)
    screen = Screen(
        decision,
        explain(decision, scenario, state),
        inventories={key: value.inventory_t for key, value in initial_state(scenario).items()},
        sources=[source.to_dict() for source in trust.sources.values()],
        rule_origin=trust_origin,
        state_origin=state_origin_label(state, snapshot),
        decision_time=state.get("decision_time"),
        forecast=(snapshot or {}).get("forecast"),
    ).payload()
    return {"ok": True, "rejected": False, "scenario_id": scenario.scenario_id,
            "decision": decision, "screen": screen, "trust_origin": trust_origin,
            "binding": binding_summary(raw) if snapshot is not None else None}

def make_interactive_demo(raw: dict, budget: int, trust_cfg: dict, trust_origin: str | None = None,
                          snapshots: list | None = None, response_model: dict | None = None) -> Demo:
    return Demo(raw, run_demo_decision, trust_cfg, budget, trust_origin=trust_origin,
                snapshots=list(snapshots or []), response_model=response_model)

def make_demo_service(root: Path, budget: int = 400, out: Path | None = None) -> DemoService:
    root = Path(root)
    out = Path(out) if out is not None else root / "artifacts"
    trust_cfg, trust_origin = load_trust_rules(root, out)
    snapshots = load_snapshots(out)
    response_model = load_response_model(root, out)
    return DemoService(root, lambda raw, budget: make_interactive_demo(raw, budget, trust_cfg, trust_origin,
                                                                     snapshots, response_model),
                       budget, snapshots=snapshots)
