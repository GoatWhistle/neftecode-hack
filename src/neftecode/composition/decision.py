from functools import partial

from neftecode.infrastructure.history.source import LocalHistorySource
from neftecode.infrastructure.artifacts.provenance import loaded_provenance
from pathlib import Path

from neftecode.application.ports.live import ForecastBindingError
from neftecode.application.use_cases.advise_under_conditions import AdviseUnderConditions, report_advice
from neftecode.application.services.tank_estimate import default_tank_estimate_factory
from neftecode.domain.advisory.optimizer import DEFAULT_BUDGET
from neftecode.infrastructure.agentic import default_decision_factory
from neftecode.infrastructure.config.scenario import ScenarioError, parse_scenario
from neftecode.infrastructure.config.trust_rules import load_trust_rules
from neftecode.infrastructure.live.response_model import load_response_model_with_digest
from neftecode.infrastructure.llm.config import decision_wait_seconds
from neftecode.infrastructure.live.snapshots import bind_snapshot, select_forecast_dict
from neftecode.infrastructure.scenarios import FileScenarioRepository, FileSnapshotRepository
from neftecode.presentation.demo import Demo, state_origin_label
from neftecode.presentation.web.server import DemoService
from neftecode.presentation.web.ui import Screen, error_payload

def run_demo_decision(raw: dict, state: dict, budget: int, trust_cfg: dict,
                      decision_factory=None, trust_origin: str | None = None,
                      snapshot: dict | None = None, response_model: dict | None = None) -> dict:
    if not isinstance(trust_cfg, dict):
        raise ValueError("trust_cfg должен быть словарём порогов доверия к источникам")
    try:
        advice = AdviseUnderConditions(
            parse_scenario, bind_snapshot, select_forecast_dict,
            decision_factory or default_decision_factory(), default_tank_estimate_factory,
        ).execute(raw, state, budget, trust_cfg, snapshot, response_model)
    except (ScenarioError, ForecastBindingError) as exc:
        return {"ok": False, "rejected": True, "reason": str(exc),
                "screen": error_payload(str(exc))}
    report_advice(advice)
    scenario, trust, active_forecast = advice["scenario"], advice["trust"], advice["forecast"]
    decision = advice["decision"]
    screen = Screen(
        decision,
        advice["explanation"], inventories=advice["inventories"],
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
            "binding": advice["binding"]}

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
    snapshots = FileSnapshotRepository(out).all()
    response_model, response_sha256 = load_response_model_with_digest(root, out)
    provenance = loaded_provenance(root, out, response_sha256)
    factory = default_decision_factory(root)
    return DemoService(root, lambda raw, budget: make_interactive_demo(raw, budget, trust_cfg, trust_origin,
                                                                     snapshots, response_model, factory),
                       FileScenarioRepository(root / "config/scenarios"), budget, snapshots=snapshots, default_snapshot_key=default_snapshot,
                       decision_timeout_s=decision_wait_seconds(root),
                       provenance=lambda: provenance, history=LocalHistorySource(root, out))
