from dataclasses import dataclass, field
import json
import threading

from neftecode.application.cancellation import check_cancelled

from neftecode.domain.advisory.optimizer import DEFAULT_BUDGET
from neftecode.application.use_cases.make_decision import MakeDecision, SearchOutcome
from neftecode.application.use_cases.plan_operation import PlannerError
from neftecode.domain.advisory.optimizer import rank

from .budget import AgentBudget
from .contracts import AgentConstraint, AgentSettings
from .session_context import SessionContextMixin
from .session_metrics import SessionMetricsMixin
from .session_support import LOOKAHEAD_CONSTRAINT_CAP, SessionError, finite

__all__ = ["LOOKAHEAD_CONSTRAINT_CAP", "DecisionSession", "SessionError"]


@dataclass
class DecisionSession(SessionMetricsMixin, SessionContextMixin):
    maker: MakeDecision
    outcome: SearchOutcome
    legacy: dict
    settings: AgentSettings
    budget: AgentBudget
    evaluation_budget: int = DEFAULT_BUDGET
    confirmed: tuple = ()
    initial_tanks: dict | None = None
    current_operation: dict | None = None
    raw_scenario: dict | None = None
    state: dict | None = None
    trust_cfg: dict | None = None
    live_context: dict | None = None
    response_effect: object | None = None
    evaluations: dict = field(init=False)
    plans: dict = field(init=False)
    constraints: list = field(init=False, default_factory=list)
    vetoes: dict = field(init=False, default_factory=dict)
    evaluated: int = field(init=False)
    _seen: set = field(init=False)
    _passes: dict = field(init=False, default_factory=dict)
    _lookahead: dict = field(init=False, default_factory=dict)
    _robustness: dict = field(init=False, default_factory=dict)
    _margins: dict = field(init=False, default_factory=dict)
    _veto_lock: threading.Lock = field(init=False, default_factory=threading.Lock, repr=False, compare=False)

    def __post_init__(self):
        self.scenario = self.maker.scenario
        self.evaluations = {e.candidate.candidate_id: e for e in self.outcome.examined}
        self.plans = dict(self.outcome.examined_by_id)
        self.evaluated = self.outcome.evaluated
        self._seen = set(self.outcome.seen_content)

    @property
    def legacy_plan_id(self) -> str | None:
        return (self.legacy.get("selected_plan") or {}).get("plan_id")

    def candidate(self, candidate_id) -> tuple:
        if not isinstance(candidate_id, str) or candidate_id not in self.evaluations:
            raise SessionError(f"unknown_candidate: {str(candidate_id)[:80]}")
        return self.evaluations[candidate_id], self.plans[candidate_id]

    def passes(self, candidate_id: str) -> bool:
        if candidate_id not in self._passes:
            self._passes[candidate_id] = self.maker.passes_review(self.evaluations[candidate_id])
        return self._passes[candidate_id]

    def feasible_ids(self) -> list[str]:
        return [cid for cid in self._ordered(self.evaluations) if self.passes(cid)]

    def allowed_ids(self) -> list[str]:
        ids = [cid for cid in self.feasible_ids() if cid not in self.vetoes]
        cheap = [c for c in self.constraints if c.type not in ("min_hours_to_violation", "require_not_fragile")]
        ids = [cid for cid in ids if all(self._satisfies(cid, c) for c in cheap)]
        for constraint in self.constraints:
            if constraint.type == "min_hours_to_violation":
                projected = ids[:LOOKAHEAD_CONSTRAINT_CAP]
                ids = [cid for cid in projected if self._hours_ok(cid, constraint.value)]
            elif constraint.type == "require_not_fragile":
                ids = [cid for cid in ids[: self.settings.max_candidates] if self._not_fragile(cid)]
        return ids

    def _ordered(self, ids) -> list[str]:
        ordered = sorted(ids, key=lambda cid: self.evaluations[cid].key())
        head = [cid for cid in (self.legacy_plan_id, "hold") if cid in ids]
        return list(dict.fromkeys(head + ordered))

    def shortlist(self, limit: int | None = None) -> list[str]:
        return self.allowed_ids()[: limit or self.settings.max_candidates]

    def veto(self, candidate_ids, role: str) -> list[str]:
        added = []
        with self._veto_lock:
            for cid in candidate_ids:
                if cid in self.evaluations:
                    self.vetoes.setdefault(cid, set()).add(role)
                    added.append(cid)
        return added

    def _satisfies(self, candidate_id: str, constraint: AgentConstraint) -> bool:
        plan = self.plans[candidate_id]
        if constraint.type == "min_quality_margin":
            margin = self.quality_margins(candidate_id)[constraint.limit]
            return finite(margin.get("min_margin")) and margin["min_margin"] >= constraint.value - 1e-9
        if constraint.type == "max_changes":
            return plan.changes <= constraint.value
        if constraint.type == "forbid_additive":
            return all(step.additive_dose <= 0 for step in plan.steps)
        if constraint.type == "max_outflow_utilization":
            utilization = self.outflow_utilization(candidate_id)["max_utilization"]
            return utilization is not None and utilization <= constraint.value + 1e-9
        if constraint.type == "constant_plans_only":
            return len(plan.steps) == 1
        raise SessionError(f"constraint_not_evaluable: {constraint.type}")

    def _pre_filter(self, plan, constraints) -> bool:
        for constraint in constraints:
            if constraint.type == "max_changes" and plan.changes > constraint.value:
                return False
            if constraint.type == "forbid_additive" and any(s.additive_dose > 0 for s in plan.steps):
                return False
            if constraint.type == "constant_plans_only" and len(plan.steps) != 1:
                return False
        return True

    def _hours_ok(self, candidate_id: str, hours: float) -> bool:
        info = self.lookahead(candidate_id)
        if not info.get("available"):
            return False
        reach = info.get("hours_to_violation")
        return reach is None or reach >= hours - 1e-9

    def _not_fragile(self, candidate_id: str) -> bool:
        result = self.robustness(candidate_id, charge=False)
        return result.get("available") is True and result.get("fragile") is False

    def add_constraints(self, constraints) -> list[AgentConstraint]:
        known = {c.key() for c in self.constraints}
        added = [c for c in constraints if c.key() not in known]
        self.constraints.extend(added)
        return added

    def search(self, constraints) -> dict:
        if not self.budget.take_replan():
            raise SessionError("replan_limit_reached")
        added = self.add_constraints(constraints)
        remaining = max(0, self.evaluation_budget - self.evaluated)
        plans, _ = self.maker.build_plans(self.evaluation_budget, self.current_operation)
        new_ids, skipped = [], 0
        for plan in plans:
            check_cancelled()
            if len(new_ids) >= remaining:
                break
            if plan.plan_id in self.evaluations or not self._pre_filter(plan, self.constraints):
                continue
            content = json.dumps([s.to_dict() for s in plan.steps], sort_keys=True, ensure_ascii=False)
            if content in self._seen:
                continue
            self._seen.add(content)
            try:
                evaluation = self.maker.evaluate_plan(plan, self.confirmed, self.initial_tanks,
                                                      self.current_operation)
            except (PlannerError, ValueError):
                skipped += 1
                continue
            self.evaluations[plan.plan_id] = evaluation
            self.plans[plan.plan_id] = plan
            new_ids.append(plan.plan_id)
        self.evaluated += len(new_ids)
        return {"constraints_added": [c.to_dict() for c in added],
                "constraints_active": [c.to_dict() for c in self.constraints],
                "newly_evaluated": len(new_ids), "newly_feasible": sum(1 for cid in new_ids if self.passes(cid)),
                "not_evaluable": skipped, "evaluation_budget_left": max(0, self.evaluation_budget - self.evaluated),
                "feasible_total": len(self.feasible_ids()), "allowed_total": len(self.allowed_ids()),
                "shortlist": [self.card(cid) for cid in self.shortlist()]}

    def rank_allowed(self) -> dict:
        allowed = [self.evaluations[cid] for cid in self.allowed_ids()]
        result = rank(allowed, hold_id="hold", min_useful_gain=float(self.scenario.policy.get("min_useful_gain", 0.0)),
                      severity_cost_tolerance_fraction=float(
                          self.scenario.policy.get("severity_cost_tolerance_fraction", 0.0)),
                      max_severity_index=(float(self.scenario.policy["max_severity_index"])
                                          if self.scenario.policy.get("max_severity_index") is not None else None))
        selected = (result.get("selected") or {}).get("candidate_id")
        return {"selected": selected, "reason": result.get("reason"),
                "alternatives": [a["candidate_id"] for a in result.get("alternatives", [])[:3]],
                "allowed_total": len(allowed), "ranking": result.get("ranking"), "_result": result}
