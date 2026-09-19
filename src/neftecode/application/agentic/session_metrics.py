from neftecode.application.use_cases.plan_operation import PlannerError
from neftecode.domain.shared.primitives import PRODUCT_LIMITS

from .session_support import SessionError, finite, rounded


class SessionMetricsMixin:

    def quality_margins(self, candidate_id: str) -> dict:
        evaluation, _ = self.candidate(candidate_id)
        if candidate_id in self._margins:
            return self._margins[candidate_id]
        out = self._margins[candidate_id] = {}
        for limit_id, (prop, direction) in PRODUCT_LIMITS.items():
            checks = [c for c in evaluation.gate.checks if c.constraint_id == f"quality.{limit_id}"]
            quantity = self.scenario.product.limits.get(limit_id)
            source = quantity.source if quantity is not None else None
            unknown = [c for c in checks if c.status == "unknown" or not finite(c.observed) or not finite(c.limit)]
            if not checks or unknown:
                out[limit_id] = {"status": "unknown", "min_margin": None, "limit_source": source,
                                 "reason": (unknown[0].reason if unknown else "нет проверок")[:160]}
                continue
            margins = [((c.limit - c.observed) if direction == "max" else (c.observed - c.limit), c) for c in checks]
            margin, worst = min(margins, key=lambda item: (item[0], item[1].time_hours or 0.0))
            out[limit_id] = {"status": "pass" if margin >= -1e-9 else "fail", "min_margin": rounded(margin),
                             "at_hours": worst.time_hours, "observed": rounded(worst.observed),
                             "limit": worst.limit, "direction": direction, "limit_source": source}
        return out

    def quality_trajectory(self, candidate_id: str, limit_id: str) -> dict:
        evaluation, _ = self.candidate(candidate_id)
        if limit_id not in PRODUCT_LIMITS:
            raise SessionError(f"unknown_limit: {str(limit_id)[:40]}")
        points = [{"t": c.time_hours, "observed": rounded(c.observed), "status": c.status}
                  for c in evaluation.gate.checks if c.constraint_id == f"quality.{limit_id}"]
        quantity = self.scenario.product.limits.get(limit_id)
        return {"limit_id": limit_id, "limit": quantity.value if quantity else None, "points": points}

    def outflow_utilization(self, candidate_id: str) -> dict:
        evaluation, _ = self.candidate(candidate_id)
        tanks = {}
        for check in evaluation.gate.checks:
            if not check.constraint_id.startswith("outflow.") or not finite(check.observed) or not finite(check.limit):
                continue
            if check.limit <= 0:
                continue
            tank = check.constraint_id.split(".", 1)[1]
            share = check.observed / check.limit
            if share > tanks.get(tank, {}).get("utilization", -1):
                tanks[tank] = {"utilization": rounded(share), "rate_tph": rounded(check.observed),
                               "limit_tph": check.limit, "at_hours": check.time_hours}
        overall = max((v["utilization"] for v in tanks.values()), default=None)
        return {"max_utilization": overall, "tanks": tanks}

    def setpoint_changes(self, candidate_id: str) -> dict:
        _, plan = self.candidate(candidate_id)
        base = self.base_controls()
        recipe, throughput, dose = self.current_recipe()
        steps = []
        for step in plan.steps:
            controls = {k: {"from": base.get(k), "to": v, "delta": rounded(v - base[k])}
                        for k, v in step.controls.items() if k in base and abs(v - base[k]) > 1e-9}
            recipe_delta = {k: rounded(step.recipe.get(k, 0.0) - recipe.get(k, 0.0))
                            for k in sorted(set(step.recipe) | set(recipe))
                            if abs(step.recipe.get(k, 0.0) - recipe.get(k, 0.0)) > 1e-9}
            steps.append({"at_hours": step.time_hours, "controls": controls, "recipe_delta": recipe_delta,
                          "throughput_delta_tph": rounded(step.throughput_tph - throughput),
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
                out[name] = {"min_share_of_range_to_bound": rounded(share), "min": low, "max": high,
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
                tanks.setdefault(parts[1], []).append({"t": check.time_hours, "t_stock": rounded(check.observed, 2)})
        return {"candidate_id": candidate_id, "tanks": tanks, "terminal": terminal,
                "terminal_rule": (self.scenario.policy or {}).get("terminal_inventory_rule")}

    def lookahead(self, candidate_id: str) -> dict:
        _, plan = self.candidate(candidate_id)
        if candidate_id in self._lookahead:
            return self._lookahead[candidate_id]
        hours = (self.scenario.policy or {}).get("lookahead_hours")
        if not finite(hours) or hours <= 0:
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
                "production_t": rounded(evaluation.production_t, 2), "cost_per_tonne": rounded(evaluation.cost_per_tonne),
                "severity_index": rounded(evaluation.severity_index), "gate_feasible": evaluation.feasible,
                "min_margins": {k: v.get("min_margin") for k, v in margins.items()},
                "max_outflow_utilization": self.outflow_utilization(candidate_id)["max_utilization"],
                "is_legacy_choice": candidate_id == self.legacy_plan_id, "is_hold": candidate_id == "hold",
                "vetoed_by": sorted(self.vetoes.get(candidate_id, ()))}
