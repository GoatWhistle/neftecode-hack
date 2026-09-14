"""The agent loop: proposal, veto, a changed search, and a decision or a refusal.

The point of separating roles here is not decoration. Each agent answers a question the others
are not allowed to answer:

* **data** — may this state carry a decision at all?
* **quality** — do the three product properties hold at every point?
* **reliability** — is the regime within what the scenario permits of the equipment?
* **optimizer** — what can be proposed and how do the survivors compare?
* **orchestrator** — who is asked, what a veto forbids next, and when to stop.

A veto is not a log line: it removes a region of the search, and the next round is demonstrably
different. The loop is bounded, so a disagreement cannot spin forever. A failed or incomplete
agent answer produces a refusal, never a decision that quietly skipped a check.
"""
from dataclasses import dataclass, field, replace
import hashlib
import json

from neftecode.domain.shared.primitives import (CONFIRMED_SCOPE, HOLD, RECOMMEND_SCENARIO, REFUSE, SCENARIO_SCOPE)
from .plan_operation import PlanOperation, PlannerError
from neftecode.domain.production.scenario import Scenario
from neftecode.application.contracts import DecisionCommand, DecisionResult
from neftecode.application.ports import RobustnessEvaluator
from ..services.trust import DataTrustAgent

#: How many times the orchestrator may ask for a changed search before giving up.
MAX_ROUNDS = 3

#: Constraint families a veto can forbid, mapped to the search restriction they imply.
VETO_FAMILIES = {
    "outflow": "снизить отбор из резервуара",
    "inventory": "уменьшить расход запаса",
    "quality": "усилить качество смеси",
    "control": "остаться в диапазоне уставок",
    "additive": "снизить дозу присадки",
    "model": "остаться в области применимости модели",
}


class AgentError(RuntimeError):
    """Raised when an agent cannot answer; never swallowed into a successful decision."""


def _family(constraint_id: str) -> str:
    return constraint_id.split(".")[0]


@dataclass
class QualityAgent:
    """Reads the gate's quality verdicts. It does not compute economics and cannot waive a limit."""

    def review(self, evaluation) -> dict:
        checks = [c for c in evaluation.gate.checks if _family(c.constraint_id) == "quality"]
        failed = [c for c in checks if c.status == "fail"]
        unknown = [c for c in checks if c.status == "unknown"]
        return {"agent": "quality", "checked": len(checks),
                "passed": len(checks) - len(failed) - len(unknown),
                "vetoes": [c.reason for c in failed],
                "unknown": [c.reason for c in unknown],
                "verdict": "fail" if failed else ("unknown" if unknown else "pass")}


@dataclass
class ReliabilityAgent:
    """Equipment and regime limits of the scenario, plus the severity index."""

    def review(self, evaluation) -> dict:
        families = ("outflow", "control", "inventory", "additive")
        checks = [c for c in evaluation.gate.checks if _family(c.constraint_id) in families]
        failed = [c for c in checks if c.status == "fail"]
        unknown = [c for c in checks if c.status == "unknown"]
        return {"agent": "reliability", "checked": len(checks),
                "passed": len(checks) - len(failed) - len(unknown),
                "vetoes": [c.reason for c in failed],
                "unknown": [c.reason for c in unknown],
                "severity_index": evaluation.severity_index,
                "verdict": "fail" if failed else ("unknown" if unknown else "pass"),
                "scope": "Ограничения оборудования заданы сценарием; это не оценка реального ресурса."}


@dataclass
class MakeDecision:
    """Runs the loop and produces the decision, or explains why there is none."""

    scenario: Scenario
    planner: PlanOperation = field(init=False)
    quality: QualityAgent = field(default_factory=QualityAgent)
    reliability: ReliabilityAgent = field(default_factory=ReliabilityAgent)
    max_rounds: int = MAX_ROUNDS
    robustness_evaluator: RobustnessEvaluator | None = None

    def __post_init__(self):
        self.planner = PlanOperation(self.scenario)

    def decide(self, state: dict | None = None, confirmed=(), budget: int = 600,
               trust_cfg: dict | None = None, raw_scenario: dict | None = None,
               initial_tanks=None, current_operation: dict | None = None) -> dict:
        trace: list[dict] = []
        state = state or {}

        # 1. Data first: a state that cannot carry a decision stops the loop before any model runs.
        if state:
            report = DataTrustAgent(trust_cfg or {}).assess(state)
            trace.append({"agent": "data", "usable": report.usable, "primary": report.primary,
                          "reasons": list(report.reasons)})
            if not report.usable:
                return self._finish(REFUSE, report.refusal_reason(), trace, None, None,
                                    {"kind": "data", "missing": list(report.missing_requirements)},
                                    current_operation=current_operation)

        # 2. Bounded proposal/veto loop.
        forbidden: set[str] = set()
        rounds = []
        selected = None
        selected_plan_obj = None
        last_result = None
        feedback: dict[str, list[str]] = {}
        evaluated_total = 0
        seen_content: set[str] = set()
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
                except (PlannerError, ValueError):
                    continue
                evaluations.append(evaluation)
                by_id[plan.plan_id] = plan
            if not evaluations:
                rounds.append({"round": round_number, "proposed": 0, "feasible": 0,
                               "candidate_ids": [p.plan_id for p in search_plans[:20]],
                               "note": "После запретов кандидатов не осталось"})
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
            from neftecode.domain.advisory.optimizer import rank
            last_result = rank(feasible or evaluations, hold_id="hold",
                               min_useful_gain=float(self.scenario.policy.get("min_useful_gain", 0.0)))
            if feasible:
                selected = last_result
                selected_plan_obj = by_id.get(selected.get("selected", {}).get("candidate_id"))
                break
            # A veto must change the next search, not merely be recorded.
            added = self._restrict(vetoes, forbidden)
            feedback = vetoes
            rounds[-1]["restriction_added"] = added
            if not added:
                rounds[-1]["note"] = "Запреты не сузили поиск: повторять бессмысленно"
                break

        trace.append({"agent": "optimizer", "rounds": rounds, "max_rounds": self.max_rounds,
                      "evaluated": evaluated_total, "evaluation_budget": budget,
                      "note": "Бюджет поиска общий; финальная проверка выбранного плана выполняется отдельно."})
        if selected is None or selected.get("selected") is None:
            reasons = sorted({r for e in (last_result or {}).get("rejected", [])
                              for r in e["rejection_reasons"]})[:5]
            return self._finish(REFUSE,
                                "Ни один вариант не проходит одновременно все обязательные проверки",
                                trace, None, None,
                                {"kind": "no_feasible_plan", "examples": reasons},
                                current_operation=current_operation)

        # 3. Re-check the chosen plan through the same gate before releasing it.
        plan_id = selected["selected"]["candidate_id"]
        plans, _ = self._build_plans(budget, current_operation)
        chosen = selected_plan_obj or next((p for p in plans if p.plan_id == plan_id), None)
        if chosen is None:
            raise AgentError(f"Выбранный план {plan_id} не найден при повторной проверке")
        final = self._evaluate_plan(chosen, confirmed, initial_tanks, current_operation)
        review = self._review(final)
        trace.append({"agent": "quality", "stage": "final", **review["quality"]})
        trace.append({"agent": "reliability", "stage": "final", **review["reliability"]})
        if not final.feasible or not self._review_passes(review):
            return self._finish(REFUSE,
                                "Повторная проверка выбранного плана не пройдена: решение не выдаётся",
                                trace, None, None,
                                {"kind": "final_recheck_failed",
                                 "examples": list(final.gate.rejection_reasons())[:5]},
                                current_operation=current_operation)

        # 4. Robustness: a plan that only holds when every coefficient is exactly right is
        #    reported as fragile rather than released as reliable.
        robustness = None
        if raw_scenario is not None and self.robustness_evaluator is not None:
            robustness = self.robustness_evaluator.evaluate(
                self.scenario, raw_scenario, chosen, confirmed, initial_tanks, current_operation)
            trace.append({"agent": "robustness", "held": robustness["held"],
                          "evaluated": robustness["perturbations_evaluated"],
                          "fragile": robustness["fragile"]})

        status = HOLD if chosen.changes == 0 else RECOMMEND_SCENARIO
        reason = ("Текущий режим проходит все обязательные проверки; изменения не требуются"
                  if status == HOLD else selected["reason"])
        if robustness is not None and robustness["fragile"]:
            reason += (f". Предупреждение: план теряет допустимость при "
                       f"{robustness['violated']} из {robustness['perturbations_evaluated']} "
                       f"заданных отклонений и надёжным не считается")
        return self._finish(
            status, reason, trace, chosen, final, None, selected, robustness,
            current_operation=current_operation,
        )

    def execute(self, command: DecisionCommand) -> DecisionResult:
        """Application entry point; accepts a mapping or explicit decision arguments."""
        if not isinstance(command, DecisionCommand):
            raise TypeError("MakeDecision.execute expects DecisionCommand")
        state = dict(command.state) if command.state is not None else None
        return self.decide(state=state, confirmed=command.confirmed,
                           budget=command.budget, trust_cfg=command.trust_cfg,
                           raw_scenario=command.raw_scenario,
                           initial_tanks=command.initial_tanks,
                           current_operation=command.current_operation)

    # --- Internals ---

    def _build_plans(self, budget, current_operation=None):
        if current_operation is not None:
            return self.planner.build_plans(budget, current_operation=current_operation)
        return self.planner.build_plans(budget)

    def _evaluate_plan(self, plan, confirmed, initial_tanks, current_operation=None):
        if current_operation is not None:
            return self.planner.evaluate(plan, confirmed, initial_tanks=initial_tanks,
                                         current_operation=current_operation)
        if initial_tanks is not None:
            return self.planner.evaluate(plan, confirmed, initial_tanks=initial_tanks)
        return self.planner.evaluate(plan, confirmed)

    @staticmethod
    def _sample_plans(plans, count):
        """Preserve hold and cover both constant and transitional plans under a total budget."""
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
                    vetoes.setdefault(_family(check.constraint_id), []).append(check.reason)
            if reviews:
                review = reviews.get(evaluation.candidate.candidate_id, {})
                for role, answer in review.items():
                    if not isinstance(answer, dict) or answer.get("verdict") == "pass":
                        continue
                    family = "quality" if role == "quality" else "control"
                    reasons = list(answer.get("vetoes", ())) + list(answer.get("unknown", ()))
                    vetoes.setdefault(family, []).extend(reasons or [f"Агент {role} не подтвердил план"])
        return vetoes

    def _feedback_candidates(self, plans, vetoes):
        """Create candidates that encode feedback; never present the same search as consensus."""
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
            candidate = replace(plan, plan_id=f"{plan.plan_id}:feedback:{','.join(sorted(families))}",
                                steps=tuple(steps), changes=max(1, plan.changes),
                                intent="План скорректирован после замечаний: " + ", ".join(sorted(families)))
            result.append(candidate)
        return result

    def _restrict(self, vetoes: dict[str, list[str]], forbidden: set[str]) -> list[str]:
        """Turn vetoes into search restrictions the next round must obey."""
        added = []
        for family in sorted(vetoes):
            token = f"family:{family}"
            if family in VETO_FAMILIES and token not in forbidden:
                forbidden.add(token)
                added.append(f"{family}: {VETO_FAMILIES[family]}")
        return added

    def _forbidden(self, plan, forbidden: set[str]) -> bool:
        """Apply the accumulated restrictions to the candidate before it is evaluated.

        The restriction is computed per tank, not against one global ceiling: a veto saying
        "the draw is too big" must remove exactly the candidates that draw too much, otherwise
        the next round would examine the same set and the loop would be theatre.
        """
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

    def _finish(self, status, reason, trace, plan, evaluation, refusal, ranking=None,
                robustness=None, current_operation=None) -> dict:
        result = {
            "status": status, "reason": reason, "scope": SCENARIO_SCOPE,
            "current_operation": current_operation,
            "commercial_release_allowed": False,
            "scenario_id": self.scenario.scenario_id,
            "selected_plan": plan.to_dict() if plan is not None else None,
            "immediate_action": plan.steps[0].to_advice_dict() if plan is not None else None,
            "gate": evaluation.gate.to_dict() if evaluation is not None else None,
            "production_t": evaluation.production_t if evaluation is not None else None,
            "cost_per_tonne": evaluation.cost_per_tonne if evaluation is not None else None,
            "severity_index": evaluation.severity_index if evaluation is not None else None,
            "alternatives": (ranking or {}).get("alternatives", []),
            "rejected": (ranking or {}).get("rejected", []),
            "refusal": refusal,
            "robustness": robustness,
            "trace": trace,
            "note": ("Результат сценарный. Выданный план не считается исполненным и не разрешает "
                     "выпуск товарного топлива."),
        }
        content = json.dumps(result, sort_keys=True, ensure_ascii=False, default=str)
        result["decision_id"] = hashlib.sha256(content.encode()).hexdigest()[:16]
        return result
