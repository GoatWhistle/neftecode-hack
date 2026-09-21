from dataclasses import dataclass
from typing import Callable

from neftecode.application.services.explain import explain
from neftecode.application.services.robustness import RobustnessCheck
from neftecode.application.services.trust import DataTrustAgent
from neftecode.application.use_cases.get_live_advice import binding_summary, decision_context
from neftecode.application.use_cases.make_decision import MakeDecision
from neftecode.domain.production.inventory import initial_state


@dataclass
class AdviseUnderConditions:
    scenario_parser: Callable
    snapshot_binder: Callable
    forecast_selector: Callable
    decision_factory: Callable | None = None
    tank_estimate_factory: Callable | None = None

    def execute(self, raw: dict, state: dict, budget: int, trust_cfg: dict,
                snapshot: dict | None = None, response_model: dict | None = None) -> dict:
        scenario = self.scenario_parser(raw)
        if snapshot is not None:
            scenario, raw = self.snapshot_binder(raw, state, snapshot, response_model, trust_cfg)
        trust = DataTrustAgent(trust_cfg).assess(state)
        active_forecast = self.forecast_selector(snapshot, trust) if snapshot is not None else None
        evaluator = RobustnessCheck(scenario, raw, scenario_parser=self.scenario_parser)
        context = (decision_context(snapshot.get("at"), active_forecast, raw)
                   if snapshot is not None else None)
        if self.decision_factory is None:
            maker = MakeDecision(
                scenario, robustness_evaluator=evaluator,
                tank_estimate_factory=self.tank_estimate_factory,
                scenario_parser=self.scenario_parser,
            )
        else:
            args = (scenario, evaluator) if context is None else (scenario, evaluator, context)
            maker = self.decision_factory(
                *args, tank_estimate_factory=self.tank_estimate_factory,
                scenario_parser=self.scenario_parser,
            )
        decision = maker.decide(state=state, budget=budget, trust_cfg=trust_cfg, raw_scenario=raw)
        return {
            "scenario": scenario,
            "raw": raw,
            "trust": trust,
            "forecast": active_forecast,
            "decision": decision,
            "explanation": explain(decision, scenario, state),
            "inventories": {key: value.inventory_t for key, value in initial_state(scenario).items()},
            "binding": binding_summary(raw) if snapshot is not None else None,
        }
