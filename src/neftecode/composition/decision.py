from functools import partial
from pathlib import Path

from neftecode.application.ports.live import ForecastBindingError
from neftecode.application.progress import emit
from neftecode.application.services.explain import explain
from neftecode.application.services.trust import DataTrustAgent
from neftecode.application.use_cases.get_live_advice import binding_summary, decision_context
from neftecode.domain.production.inventory import initial_state
from neftecode.application.services.robustness import RobustnessCheck
from neftecode.application.services.tank_estimate import default_tank_estimate_factory
from neftecode.domain.advisory.optimizer import DEFAULT_BUDGET
from neftecode.infrastructure.agentic import default_decision_factory
from neftecode.infrastructure.config.scenario import ScenarioError, parse_scenario
from neftecode.infrastructure.config.trust_rules import load_trust_rules
from neftecode.infrastructure.live.advisor import load_response_model
from neftecode.infrastructure.llm.config import decision_wait_seconds
from neftecode.infrastructure.live.snapshots import bind_snapshot, load_snapshots, select_forecast_dict
from neftecode.presentation.demo import Demo, state_origin_label
from neftecode.presentation.web.server import DemoService
from neftecode.presentation.web.ui import Screen, error_payload

def run_demo_decision(raw: dict, state: dict, budget: int, trust_cfg: dict,
                      decision_factory=None, trust_origin: str | None = None,
                      snapshot: dict | None = None, response_model: dict | None = None) -> dict:
    if not isinstance(trust_cfg, dict):
        raise ValueError("trust_cfg должен быть словарём порогов доверия к источникам")
    try:
        scenario = parse_scenario(raw)
        if snapshot is not None:
            scenario, raw = bind_snapshot(raw, state, snapshot, response_model, trust_cfg)
    except (ScenarioError, ForecastBindingError) as exc:
        return {"ok": False, "rejected": True, "reason": str(exc),
                "screen": error_payload(str(exc))}
    emit("phase", key="scenario", state="done")
    trust = DataTrustAgent(trust_cfg).assess(state)
    active_forecast = select_forecast_dict(snapshot, trust) if snapshot is not None else None
    emit("stage", stage="state", inventories={key: value.inventory_t
                                              for key, value in initial_state(scenario).items()})
    emit("stage", stage="trust", sources=[source.to_dict() for source in trust.sources.values()],
         usable=trust.usable)
    factory = decision_factory or default_decision_factory()
    evaluator = RobustnessCheck(scenario, raw, scenario_parser=parse_scenario)
    maker = (factory(scenario, evaluator, tank_estimate_factory=default_tank_estimate_factory,
                     scenario_parser=parse_scenario) if snapshot is None else
             factory(scenario, evaluator, decision_context(snapshot.get("at"), active_forecast, raw),
                    tank_estimate_factory=default_tank_estimate_factory, scenario_parser=parse_scenario))
    emit("phase", key="solving", state="running")
    decision = maker.decide(state=state, budget=budget, trust_cfg=trust_cfg, raw_scenario=raw)
    emit("phase", key="solving", state="done")
    screen = Screen(
        decision,
        explain(decision, scenario, state),
        inventories={key: value.inventory_t for key, value in initial_state(scenario).items()},
        sources=[source.to_dict() for source in trust.sources.values()],
        rule_origin=trust_origin,
        state_origin=state_origin_label(state, snapshot),
        decision_time=state.get("decision_time"),
        forecast=active_forecast,
        forecast_used=(bool(trust.usable and (active_forecast or {}).get("available"))
                       if snapshot is not None else None),
    ).payload()
    return {"ok": True, "rejected": False, "scenario_id": scenario.scenario_id,
            "decision": decision, "screen": screen, "trust_origin": trust_origin,
            "binding": binding_summary(raw) if snapshot is not None else None}

def make_interactive_demo(raw: dict, budget: int, trust_cfg: dict, trust_origin: str | None = None,
                          snapshots: list | None = None, response_model: dict | None = None,
                          decision_factory=None) -> Demo:
    runner = (run_demo_decision if decision_factory is None
              else partial(run_demo_decision, decision_factory=decision_factory))
    return Demo(raw, runner, trust_cfg, budget, trust_origin=trust_origin,
                snapshots=list(snapshots or []), response_model=response_model)

def make_demo_service(root: Path, budget: int = DEFAULT_BUDGET, out: Path | None = None,
                      default_snapshot: str | None = None) -> DemoService:
    root = Path(root)
    out = Path(out) if out is not None else root / "artifacts"
    trust_cfg, trust_origin = load_trust_rules(root, out)
    snapshots = load_snapshots(out)
    response_model = load_response_model(root, out)
    factory = default_decision_factory(root)
    return DemoService(root, lambda raw, budget: make_interactive_demo(raw, budget, trust_cfg, trust_origin,
                                                                     snapshots, response_model, factory),
                       budget, snapshots=snapshots, default_snapshot_key=default_snapshot,
                       decision_timeout_s=decision_wait_seconds(root))
