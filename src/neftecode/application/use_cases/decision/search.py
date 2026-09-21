from dataclasses import replace
import json

from neftecode.domain.advisory.optimizer import rank
from ..plan_operation import PlannerError
from .reviews import family
from .constants import VETO_FAMILIES, AgentError, SearchOutcome


class SearchMixin:

    def _search(self, budget: int, confirmed=(), initial_tanks=None, current_operation=None) -> "SearchOutcome":
        forbidden: set[str] = set()
        rounds = []
        selected = None
        selected_plan_obj = None
        last_result = None
        feedback: dict[str, list[str]] = {}
        evaluated_total = 0
        seen_content: set[str] = set()
        feasible, by_id = [], {}
        examined, examined_by_id = [], {}
        computation_errors: list[dict] = []
        for round_number in range(1, self.max_rounds + 1):
            remaining = budget - evaluated_total
            if remaining <= 0:
                rounds.append({"round": round_number, "proposed": 0, "feasible": 0,
                               "note": "Общий бюджет проверки исчерпан"})
                break
            try:
                round_budget = min(remaining, max(1, budget // 2)) if round_number == 1 else remaining
                plans, info = self._build_plans(budget, current_operation)
            except (PlannerError, ValueError) as exc:
                raise AgentError(f"Оптимизатор не смог построить кандидатов: {exc}") from exc
            if round_number == 1:
                search_plans = self._sample_plans(plans, round_budget)
            else:
                search_plans = self._feedback_candidates(plans, feedback)
            evaluations, by_id = [], {}
            round_evaluated = 0
            for plan in search_plans:
                if evaluated_total >= budget or round_evaluated >= round_budget:
                    break
                if self._forbidden(plan, forbidden):
                    continue
                try:
                    content = json.dumps([s.to_dict() for s in plan.steps], sort_keys=True, ensure_ascii=False)
                    if content in seen_content:
                        continue
                    seen_content.add(content)
                    evaluated_total += 1
                    round_evaluated += 1
                    evaluation = self._evaluate_plan(
                        plan, confirmed, initial_tanks, current_operation
                    )
                except (PlannerError, ValueError) as exc:
                    computation_errors.append({"round": round_number, "plan_id": plan.plan_id,
                                               "error": str(exc)})
                    continue
                evaluations.append(evaluation)
                by_id[plan.plan_id] = plan
                examined.append(evaluation)
                examined_by_id[plan.plan_id] = plan
            if not evaluations:
                round_errors = [e for e in computation_errors if e["round"] == round_number]
                if search_plans and round_errors:
                    note = "Все кандидаты раунда упали с технической ошибкой вычисления"
                else:
                    note = "После запретов кандидатов не осталось"
                rounds.append({"round": round_number, "proposed": 0, "feasible": 0,
                               "candidate_ids": [p.plan_id for p in search_plans[:20]],
                               "note": note})
                break

            reviews_by_id = {e.candidate.candidate_id: self._review(e) for e in evaluations}
            reviews = list(reviews_by_id.values())
            feasible = [e for e in evaluations
                        if e.feasible and self._review_passes(reviews_by_id.get(e.candidate.candidate_id))]
            vetoes = self._collect_vetoes(evaluations, reviews_by_id)
            rounds.append({
                "round": round_number, "proposed": len(evaluations), "feasible": len(feasible),
                "forbidden_before": sorted(forbidden),
                "veto_families": {k: len(v) for k, v in vetoes.items()},
                "quality_vetoed": sum(1 for r in reviews if r["quality"]["verdict"] == "fail"),
                "reliability_vetoed": sum(1 for r in reviews if r["reliability"]["verdict"] == "fail"),
                "candidate_ids": [p.plan_id for p in search_plans[:20]],
            })
            last_result = rank(feasible or evaluations, hold_id="hold", min_useful_gain=self._min_useful_gain(),
                               severity_cost_tolerance_fraction=self._severity_cost_tolerance(),
                               max_severity_index=self._max_severity_index())
            if feasible:
                selected = last_result
                selected_plan_obj = by_id.get(selected.get("selected", {}).get("candidate_id"))
                break
            added = self._restrict(vetoes, forbidden)
            feedback = vetoes
            rounds[-1]["restriction_added"] = added
            if not added:
                rounds[-1]["note"] = "Запреты не сузили поиск: повторять бессмысленно"
                break
        return SearchOutcome(selected=selected, selected_plan=selected_plan_obj, feasible=feasible, by_id=by_id,
                             rounds=rounds, evaluated=evaluated_total, last_result=last_result,
                             examined=examined, examined_by_id=examined_by_id, seen_content=seen_content,
                             forbidden=frozenset(forbidden), computation_errors=computation_errors)

    @staticmethod
    def _sample_plans(plans, count):
        if len(plans) <= count:
            return plans
        singles = [p for p in plans if len(p.steps) == 1]
        transitions = [p for p in plans if len(p.steps) > 1]
        nt = min(len(transitions), count // 4)
        ns = min(len(singles), count - nt)
        nt = min(len(transitions), count - ns)
        def spread(items, n):
            if n <= 0:
                return []
            return [items[round(i * (len(items) - 1) / max(1, n - 1))] for i in range(n)]
        return spread(singles, ns) + spread(transitions, nt)

    def _review(self, evaluation) -> dict:
        return {"quality": self._safe_review(self.quality, evaluation, "quality"),
                "reliability": self._safe_review(self.reliability, evaluation, "reliability")}

    @staticmethod
    def _safe_review(agent, evaluation, name: str) -> dict:
        try:
            answer = agent.review(evaluation)
        except Exception as exc:
            return {"agent": name, "checked": 0, "passed": 0, "vetoes": [],
                    "unknown": [f"Агент {name} не ответил: {exc}"], "verdict": "unknown"}
        required = {"agent", "checked", "passed", "vetoes", "unknown", "verdict"}
        if (not isinstance(answer, dict) or answer.get("verdict") not in ("pass", "fail", "unknown")
                or not required.issubset(answer)
                or not isinstance(answer.get("vetoes"), (list, tuple))
                or not isinstance(answer.get("unknown"), (list, tuple))
                or not isinstance(answer.get("checked"), int) or answer.get("checked") <= 0
                or not isinstance(answer.get("passed"), int)
                or answer.get("passed") != answer.get("checked") - len(answer.get("vetoes")) - len(answer.get("unknown"))
                or (answer.get("verdict") == "pass" and (answer.get("vetoes") or answer.get("unknown")))):
            return {"agent": name, "checked": 0, "passed": 0, "vetoes": [],
                    "unknown": [f"Агент {name} вернул неполный ответ"], "verdict": "unknown"}
        return answer

    @staticmethod
    def _review_passes(review: dict | None) -> bool:
        return bool(review) and all(review.get(role, {}).get("verdict") == "pass"
                                    for role in ("quality", "reliability"))

    @staticmethod
    def _collect_vetoes(evaluations, reviews=None) -> dict[str, list[str]]:
        vetoes: dict[str, list[str]] = {}
        for evaluation in evaluations:
            for check in evaluation.gate.checks:
                if check.status in ("fail", "unknown"):
                    vetoes.setdefault(family(check.constraint_id), []).append(check.reason)
            if reviews:
                review = reviews.get(evaluation.candidate.candidate_id, {})
                for role, answer in review.items():
                    if not isinstance(answer, dict) or answer.get("verdict") == "pass":
                        continue
                    name = "quality" if role == "quality" else "control"
                    reasons = list(answer.get("vetoes", ())) + list(answer.get("unknown", ()))
                    vetoes.setdefault(name, []).extend(reasons or [f"Агент {role} не подтвердил план"])
        return vetoes

    def _feedback_candidates(self, plans, vetoes):
        families = set(vetoes)
        if not families:
            return []
        result = []
        low_sulfur = min((t for t in self.scenario.tanks if t.available),
                         key=lambda t: t.property_value("sulfur_mgkg"))
        for plan in plans:
            steps = []
            for spec in plan.steps:
                controls = dict(spec.controls)
                recipe = dict(spec.recipe)
                throughput = spec.throughput_tph
                if "quality" in families:
                    recipe = {low_sulfur.tank_id: 1.0}
                if "inventory" in families or "outflow" in families:
                    throughput = max(0.0, throughput * 0.5)
                if "control" in families:
                    for stage in self.scenario.stages.values():
                        for name, bounds in stage.controls.items():
                            if name in controls:
                                controls[name] = min(bounds["max"].value,
                                                     max(bounds["min"].value, controls[name]))
                steps.append(replace(spec, controls=controls, recipe=recipe,
                                     throughput_tph=throughput))
            joined = ",".join(sorted(families))
            candidate = replace(plan, plan_id=f"{plan.plan_id}:feedback:{joined}",
                                steps=tuple(steps), changes=max(1, plan.changes),
                                intent="План скорректирован после замечаний: " + ", ".join(sorted(families)))
            result.append(candidate)
        return result

    def _restrict(self, vetoes: dict[str, list[str]], forbidden: set[str]) -> list[str]:
        added = []
        for name in sorted(vetoes):
            token = f"family:{name}"
            if name in VETO_FAMILIES and token not in forbidden:
                forbidden.add(token)
                added.append(f"{name}: {VETO_FAMILIES[name]}")
        return added

    def _forbidden(self, plan, forbidden: set[str]) -> bool:
        if "family:outflow" in forbidden or "family:inventory" in forbidden:
            limits = {t.tank_id: t.max_outflow.value for t in self.scenario.tanks}
            for step in plan.steps:
                for tank_id, fraction in step.recipe.items():
                    if fraction <= 1e-12:
                        continue
                    limit = limits.get(tank_id)
                    if limit is None or step.throughput_tph * fraction > limit + 1e-9:
                        return True
        if "family:additive" in forbidden and any(s.additive_dose > 0 for s in plan.steps):
            return True
        return False
