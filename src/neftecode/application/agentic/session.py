"""The deterministic environment agents act in.

A session holds what the legacy search already evaluated and computes every figure an agent may see from
the gate's own checks, the plan steps and the scenario. Nothing here decides feasibility: that stays with
the gate. Agent constraints only remove plans from the set the gate and the validators already accepted.
"""
from dataclasses import dataclass, field
import json
import math

from neftecode.application.services.trust import DataTrustAgent
from neftecode.application.use_cases.make_decision import MakeDecision, SearchOutcome
from neftecode.application.use_cases.plan_operation import PlannerError
from neftecode.domain.advisory.optimizer import rank
from neftecode.domain.shared.primitives import PRODUCT_LIMITS

from .budget import AgentBudget
from .contracts import AgentConstraint, AgentSettings

#: How many allowed plans an expensive constraint (look-ahead) may project, in ranking order.
LOOKAHEAD_CONSTRAINT_CAP = 40


class SessionError(ValueError):
    """A tool request that cannot be answered (unknown candidate, exhausted limit, missing input)."""


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _round(value, digits: int = 4):
    return round(value, digits) if _finite(value) else value


@dataclass
class DecisionSession:
    maker: MakeDecision
    outcome: SearchOutcome
    legacy: dict
    settings: AgentSettings
    budget: AgentBudget
    evaluation_budget: int = 400
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

    def __post_init__(self):
        self.scenario = self.maker.scenario
        self.evaluations = {e.candidate.candidate_id: e for e in self.outcome.examined}
        self.plans = dict(self.outcome.examined_by_id)
        self.evaluated = self.outcome.evaluated
        self._seen = set(self.outcome.seen_content)

    # --- Identity and sets ---

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
        """Gate-feasible, validator-passing plans that satisfy every accepted constraint and carry no veto."""
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
        """Legacy choice first, then hold, then the declared ranking key."""
        ordered = sorted(ids, key=lambda cid: self.evaluations[cid].key())
        head = [cid for cid in (self.legacy_plan_id, "hold") if cid in ids]
        return list(dict.fromkeys(head + ordered))

    def shortlist(self, limit: int | None = None) -> list[str]:
        return self.allowed_ids()[: limit or self.settings.max_candidates]

    def veto(self, candidate_ids, role: str) -> list[str]:
        added = []
        for cid in candidate_ids:
            if cid in self.evaluations:
                self.vetoes.setdefault(cid, set()).add(role)
                added.append(cid)
        return added

    # --- Constraints ---

    def _satisfies(self, candidate_id: str, constraint: AgentConstraint) -> bool:
        evaluation, plan = self.evaluations[candidate_id], self.plans[candidate_id]
        if constraint.type == "min_quality_margin":
            margin = self.quality_margins(candidate_id)[constraint.limit]
            return _finite(margin.get("min_margin")) and margin["min_margin"] >= constraint.value - 1e-9
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
        """Constraints decidable from the plan alone, applied before spending evaluation budget."""
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
        """Accept narrowing constraints and evaluate plans the legacy search has not examined yet."""
        if not self.budget.take_replan():
            raise SessionError("replan_limit_reached")
        added = self.add_constraints(constraints)
        remaining = max(0, self.evaluation_budget - self.evaluated)
        plans, _ = self.maker.build_plans(self.evaluation_budget, self.current_operation)
        new_ids, skipped = [], 0
        for plan in plans:
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
        result = rank(allowed, hold_id="hold", min_useful_gain=float(self.scenario.policy.get("min_useful_gain", 0.0)))
        selected = (result.get("selected") or {}).get("candidate_id")
        return {"selected": selected, "reason": result.get("reason"),
                "alternatives": [a["candidate_id"] for a in result.get("alternatives", [])[:3]],
                "allowed_total": len(allowed), "ranking": result.get("ranking"), "_result": result}

    # --- Figures derived from the gate and the plan ---

    def quality_margins(self, candidate_id: str) -> dict:
        evaluation, _ = self.candidate(candidate_id)
        if candidate_id in self._margins:
            return self._margins[candidate_id]
        out = self._margins[candidate_id] = {}
        for limit_id, (prop, direction) in PRODUCT_LIMITS.items():
            checks = [c for c in evaluation.gate.checks if c.constraint_id == f"quality.{limit_id}"]
            quantity = self.scenario.product.limits.get(limit_id)
            source = quantity.source if quantity is not None else None
            unknown = [c for c in checks if c.status == "unknown" or not _finite(c.observed) or not _finite(c.limit)]
            if not checks or unknown:
                out[limit_id] = {"status": "unknown", "min_margin": None, "limit_source": source,
                                 "reason": (unknown[0].reason if unknown else "нет проверок")[:160]}
                continue
            margins = [((c.limit - c.observed) if direction == "max" else (c.observed - c.limit), c) for c in checks]
            margin, worst = min(margins, key=lambda item: (item[0], item[1].time_hours or 0.0))
            out[limit_id] = {"status": "pass" if margin >= -1e-9 else "fail", "min_margin": _round(margin),
                             "at_hours": worst.time_hours, "observed": _round(worst.observed),
                             "limit": worst.limit, "direction": direction, "limit_source": source}
        return out

    def quality_trajectory(self, candidate_id: str, limit_id: str) -> dict:
        evaluation, _ = self.candidate(candidate_id)
        if limit_id not in PRODUCT_LIMITS:
            raise SessionError(f"unknown_limit: {str(limit_id)[:40]}")
        points = [{"t": c.time_hours, "observed": _round(c.observed), "status": c.status}
                  for c in evaluation.gate.checks if c.constraint_id == f"quality.{limit_id}"]
        quantity = self.scenario.product.limits.get(limit_id)
        return {"limit_id": limit_id, "limit": quantity.value if quantity else None, "points": points}

    def outflow_utilization(self, candidate_id: str) -> dict:
        evaluation, _ = self.candidate(candidate_id)
        tanks = {}
        for check in evaluation.gate.checks:
            if not check.constraint_id.startswith("outflow.") or not _finite(check.observed) or not _finite(check.limit):
                continue
            if check.limit <= 0:
                continue
            tank = check.constraint_id.split(".", 1)[1]
            share = check.observed / check.limit
            if share > tanks.get(tank, {}).get("utilization", -1):
                tanks[tank] = {"utilization": _round(share), "rate_tph": _round(check.observed),
                               "limit_tph": check.limit, "at_hours": check.time_hours}
        overall = max((v["utilization"] for v in tanks.values()), default=None)
        return {"max_utilization": overall, "tanks": tanks}

    def base_controls(self) -> dict:
        base = self.maker.planner.base_controls()
        if self.current_operation is not None:
            base.update(self.current_operation["controls"])
        return base

    def current_recipe(self) -> tuple[dict, float, float]:
        if self.current_operation is not None:
            return (dict(self.current_operation["recipe"]), self.current_operation["throughput_tph"],
                    self.current_operation.get("additive_dose", 0.0))
        operation = self.scenario.current_operation
        return dict(operation.recipe), operation.throughput.value, 0.0

    def setpoint_changes(self, candidate_id: str) -> dict:
        _, plan = self.candidate(candidate_id)
        base = self.base_controls()
        recipe, throughput, dose = self.current_recipe()
        steps = []
        for step in plan.steps:
            controls = {k: {"from": base.get(k), "to": v, "delta": _round(v - base[k])}
                        for k, v in step.controls.items() if k in base and abs(v - base[k]) > 1e-9}
            recipe_delta = {k: _round(step.recipe.get(k, 0.0) - recipe.get(k, 0.0))
                            for k in sorted(set(step.recipe) | set(recipe))
                            if abs(step.recipe.get(k, 0.0) - recipe.get(k, 0.0)) > 1e-9}
            steps.append({"at_hours": step.time_hours, "controls": controls, "recipe_delta": recipe_delta,
                          "throughput_delta_tph": _round(step.throughput_tph - throughput),
                          "additive_dose": step.additive_dose})
        return {"candidate_id": candidate_id, "changes": plan.changes, "plan_kind": self.plan_kind(plan),
                "intent": plan.intent[:160], "steps": steps}

    def control_margins(self, candidate_id: str) -> dict:
        _, plan = self.candidate(candidate_id)
        out = {}
        for stage in self.scenario.stages.values():
            for name, spec in stage.controls.items():
                low, high = spec["min"].value, spec["max"].value
                values = [s.controls[name] for s in plan.steps if name in s.controls]
                if not values or high <= low:
                    continue
                share = min(min(v - low, high - v) for v in values) / (high - low)
                out[name] = {"min_share_of_range_to_bound": _round(share), "min": low, "max": high,
                             "values": values}
        worst = min((v["min_share_of_range_to_bound"] for v in out.values()), default=None)
        return {"candidate_id": candidate_id, "worst": worst, "controls": out}

    def tank_projection(self, candidate_id: str) -> dict:
        evaluation, _ = self.candidate(candidate_id)
        tanks: dict[str, list] = {}
        terminal = None
        for check in evaluation.gate.checks:
            if check.constraint_id == "inventory.terminal":
                terminal = {"status": check.status, "reason": check.reason[:160]}
                continue
            parts = check.constraint_id.split(".")
            if parts[0] == "inventory" and len(parts) == 2 and parts[1] != "availability":
                tanks.setdefault(parts[1], []).append({"t": check.time_hours, "t_stock": _round(check.observed, 2)})
        return {"candidate_id": candidate_id, "tanks": tanks, "terminal": terminal,
                "terminal_rule": (self.scenario.policy or {}).get("terminal_inventory_rule")}

    def lookahead(self, candidate_id: str) -> dict:
        _, plan = self.candidate(candidate_id)
        if candidate_id in self._lookahead:
            return self._lookahead[candidate_id]
        hours = (self.scenario.policy or {}).get("lookahead_hours")
        if not _finite(hours) or hours <= 0:
            result = {"available": False, "reason": "lookahead_hours не задан политикой сценария"}
        else:
            try:
                info = self.maker.planner.lookahead(plan, hours, self.confirmed, self.initial_tanks,
                                                    self.current_operation)
                result = {"available": True, **{k: info[k] for k in ("lookahead_hours", "hours_to_violation",
                                                                    "constraint", "observed", "limit",
                                                                    "stock_ends_at_hours")},
                          "min_reaction_hours": (self.scenario.policy or {}).get("min_reaction_hours")}
            except (PlannerError, ValueError) as exc:
                result = {"available": False, "reason": str(exc)[:160]}
        self._lookahead[candidate_id] = result
        return result

    def robustness(self, candidate_id: str, charge: bool = True) -> dict:
        _, plan = self.candidate(candidate_id)
        if candidate_id in self._robustness:
            return self._robustness[candidate_id]
        evaluator = self.maker.robustness_evaluator
        if evaluator is None or self.raw_scenario is None:
            return {"available": False, "reason": "проверка устойчивости не подключена"}
        if charge and not self.budget.take_robustness():
            raise SessionError("robustness_limit_reached")
        report = evaluator.evaluate(self.scenario, self.raw_scenario, plan, self.confirmed, self.initial_tanks,
                                    self.current_operation)
        violated = [{"perturbation": r["perturbation"],
                     "first_violation": (r.get("first_violation") or {}).get("constraint_id")}
                    for r in report["results"] if r["outcome"] == "violated"][:5]
        result = {"available": True, "held": report["held"], "evaluated": report["perturbations_evaluated"],
                  "not_applicable": report.get("not_applicable", 0), "fragile": report["fragile"], "violated": violated}
        self._robustness[candidate_id] = result
        return result

    def hard_constraints(self, candidate_id: str) -> dict:
        evaluation, _ = self.candidate(candidate_id)
        statuses = {"pass": 0, "fail": 0, "unknown": 0}
        for check in evaluation.gate.checks:
            statuses[check.status] += 1
        return {"candidate_id": candidate_id, "gate_feasible": evaluation.feasible,
                "validators_pass": self.passes(candidate_id), "checks": statuses,
                "rejection_reasons": [r[:160] for r in evaluation.gate.rejection_reasons()[:5]]}

    @staticmethod
    def plan_kind(plan) -> str:
        return "constant" if len(plan.steps) == 1 else "transitional"

    def card(self, candidate_id: str) -> dict:
        evaluation, plan = self.candidate(candidate_id)
        margins = self.quality_margins(candidate_id)
        return {"id": candidate_id, "kind": self.plan_kind(plan), "changes": plan.changes,
                "production_t": _round(evaluation.production_t, 2), "cost_per_tonne": _round(evaluation.cost_per_tonne),
                "severity_index": _round(evaluation.severity_index), "gate_feasible": evaluation.feasible,
                "min_margins": {k: v.get("min_margin") for k, v in margins.items()},
                "max_outflow_utilization": self.outflow_utilization(candidate_id)["max_utilization"],
                "is_legacy_choice": candidate_id == self.legacy_plan_id, "is_hold": candidate_id == "hold",
                "vetoed_by": sorted(self.vetoes.get(candidate_id, ()))}

    # --- Context the agents start from ---

    def data_trust(self) -> dict:
        if not self.state:
            return {"state_provided": False, "note": "Сценарный запуск без измерений: доверие к данным не оценивалось"}
        report = DataTrustAgent(self.trust_cfg or {}).assess(self.state)
        return {"state_provided": True, "usable": report.usable, "primary": report.primary,
                "fallback_mode": report.fallback_mode, "telemetry_missing_fraction": report.telemetry_missing_fraction,
                "sources": {name: {"usable": v.usable, "status": v.status, "age_hours": _round(v.age_hours, 2),
                                   "max_age_hours": v.max_age_hours, "reasons": [r[:120] for r in v.reasons][:3]}
                            for name, v in report.sources.items()},
                "reasons": [r[:160] for r in report.reasons][:4]}

    def forecast(self) -> dict:
        main = next((t for t in self.scenario.tanks if t.tank_id == "main" or t.sulfur_from_chain),
                    self.scenario.tanks[0])
        prop = main.properties.get("sulfur_mgkg")
        out = {"main_tank": main.tank_id,
               "inflow_sulfur_source": ("bound_forecast_upper" if main.inflow_sulfur is not None else
                                        "chain_model" if main.sulfur_from_chain else "scenario_value"),
               "inflow_sulfur_mgkg": main.inflow_sulfur.value if main.inflow_sulfur is not None else None,
               "tank_sulfur_mgkg": prop.value if prop is not None else None,
               "tank_sulfur_source": prop.source if prop is not None else None}
        live = (self.live_context or {}).get("forecast")
        if isinstance(live, dict):
            out["live_forecast"] = {k: live.get(k) for k in ("model", "value", "lower", "upper", "available")}
            out["live_forecast"]["reason"] = str(live.get("reason") or "")[:160]
        return out

    def measurements(self) -> dict:
        """Живая привязка момента: измеренные теги, происхождение уставок и отклика, окно резервуара, предупреждения."""
        binding = (self.live_context or {}).get("binding")
        if not isinstance(binding, dict):
            return {"live": False, "note": "Сценарный запуск: измерений на момент решения нет"}
        tags = ((binding.get("measurement_binding") or {}).get("tags") or {})
        model = binding.get("response_model") or {}
        return {"live": True, "at": (self.live_context or {}).get("at"),
                "tags": {tag: (None if not isinstance(v, dict) else
                               {"value": _round(v.get("value")), "age_min": v.get("age_min")})
                         for tag, v in tags.items()},
                "controls": binding.get("controls"),
                "response_model": {k: model.get(k) for k in ("provenance", "beta_mgkg_per_c", "beta_ci",
                                                             "weak_strong", "reference_temp_c", "envelope_dt_c")},
                "tank_inflow": binding.get("tank_inflow"),
                "tank_level_window_hours": binding.get("tank_level_window_hours"),
                "notes": list((binding.get("measurement_binding") or {}).get("notes") or [])[:4],
                "warnings": [str(w)[:300] for w in (binding.get("measurement_binding") or {}).get("warnings") or []][:3]}

    def limits(self) -> dict:
        out = {limit_id: ({"value": q.value, "unit": q.unit, "source": q.source} if q is not None else None)
               for limit_id, q in self.scenario.product.limits.items()}
        margin = (self.scenario.policy or {}).get("sulfur_operating_margin_mgkg")
        if _finite(margin):
            out["sulfur_operating_margin_mgkg"] = {"value": margin, "unit": "мг/кг",
                                                   "source": "практика установки, Q&A 15.09 (1–2 ppm)"}
        return out

    def operating_state(self) -> dict:
        base = self.base_controls()
        recipe, throughput, dose = self.current_recipe()
        controls = {}
        for stage_id, stage in self.scenario.stages.items():
            for name, spec in stage.controls.items():
                actuation = spec.get("actuation")
                controls[name] = {"stage": stage_id, "current": base.get(name), "min": spec["min"].value,
                                  "max": spec["max"].value, "step": spec["step"].value if spec.get("step") else None,
                                  "actuation": getattr(actuation, "kind", None)}
        return {"controls": controls, "recipe": recipe, "throughput_tph": throughput, "additive_dose": dose,
                "tanks": {t.tank_id: {"available": t.available, "inventory_t": t.inventory.value,
                                      "max_outflow_tph": t.max_outflow.value} for t in self.scenario.tanks},
                "confirmed_actions": [{"applied_at_hours": at, "controls": dict(c)} for at, c in self.confirmed][:5],
                "max_additive_dose": self.scenario.additive.max_dose_fraction.value if self.scenario.additive else None}

    def legacy_summary(self) -> dict:
        refusal = self.legacy.get("refusal") or {}
        lookahead = self.legacy.get("lookahead") or {}
        robustness = self.legacy.get("robustness") or {}
        return {"status": self.legacy.get("status"), "selected": self.legacy_plan_id,
                "reason": str(self.legacy.get("reason") or "")[:300], "refusal_kind": refusal.get("kind"),
                "lookahead_warning": (lookahead.get("warning") or None) and str(lookahead["warning"])[:200],
                "fragile": robustness.get("fragile")}

    def search_summary(self) -> dict:
        return {"evaluated": self.evaluated, "evaluation_budget": self.evaluation_budget,
                "feasible": len(self.feasible_ids()), "allowed": len(self.allowed_ids()),
                "rounds": len(self.outcome.rounds),
                "constraints_active": [c.to_dict() for c in self.constraints]}

    def response_effect_for(self, delta_t_c: float) -> dict:
        if not _finite(delta_t_c) or abs(delta_t_c) > 2.0:
            raise SessionError("delta_t_c_out_of_range: допустимо [-2, 2] °C")
        data_model = (dict(self.response_effect.effect(self.live_context or {}, delta_t_c))
                      if self.response_effect is not None else
                      {"available": False, "reason": "адаптер эффекта отклика не подключён"})
        name = "ht_reactor_inlet_temp_c"
        base = self.base_controls()
        scenario_model = {"available": False, "reason": "нет оценённого кандидата с таким шагом температуры"}
        hold = self.evaluations.get("hold")
        if name in base and hold is not None:
            recipe, throughput, _ = self.current_recipe()
            for cid, plan in self.plans.items():
                step = plan.steps[0]
                if (len(plan.steps) == 1 and abs(step.controls.get(name, base[name]) - base[name] - delta_t_c) < 1e-6
                        and all(abs(step.controls.get(k, v) - v) < 1e-9 for k, v in base.items() if k != name)
                        and all(abs(step.recipe.get(k, 0.0) - recipe.get(k, 0.0)) < 1e-9 for k in set(step.recipe) | set(recipe))
                        and abs(step.throughput_tph - throughput) < 1e-9 and step.additive_dose == 0):
                    moved = self.quality_margins(cid)["sulfur_mgkg"].get("min_margin")
                    held = self.quality_margins("hold")["sulfur_mgkg"].get("min_margin")
                    if _finite(moved) and _finite(held):
                        scenario_model = {"available": True, "candidate_id": cid,
                                          "sulfur_margin_change_mgkg": _round(moved - held),
                                          "note": "Сценарная модель цепочки за горизонт 3 ч, не модель по данным"}
                    break
        return {"delta_t_c": delta_t_c, "data_model": data_model, "scenario_model": scenario_model}
