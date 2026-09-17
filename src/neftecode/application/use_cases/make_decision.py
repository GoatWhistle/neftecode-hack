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
import math

from neftecode.domain.shared.primitives import (CONFIRMED_SCOPE, HOLD, RECOMMEND_SCENARIO, REFUSE, SCENARIO_SCOPE)
from .plan_operation import PlanOperation, PlannerError
from neftecode.domain.advisory.optimizer import rank
from neftecode.domain.advisory.response_guard import moves_temperature, weak_response_raw
from neftecode.domain.production.scenario import Scenario
from neftecode.application.contracts import DataRejection, DecisionCommand, DecisionResult
from neftecode.application.ports import RobustnessEvaluator
from ..services.trust import DataTrustAgent

#: How many times the orchestrator may ask for a changed search before giving up.
MAX_ROUNDS = 3

#: How many feasible alternatives the look-ahead may project when the chosen plan fails early.
LOOKAHEAD_CANDIDATES = 40

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


@dataclass
class SearchOutcome:
    """What the bounded search examined and chose.

    `feasible` and `by_id` belong to the round that produced the choice (or the last round);
    `examined` and `examined_by_id` cover every round, so a later step can avoid repeating work.
    """

    selected: dict | None
    selected_plan: object | None
    feasible: list
    by_id: dict
    rounds: list[dict]
    evaluated: int
    last_result: dict | None
    examined: list = field(default_factory=list)
    examined_by_id: dict = field(default_factory=dict)
    seen_content: set[str] = field(default_factory=set)
    forbidden: frozenset[str] = frozenset()


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
               initial_tanks=None, current_operation: dict | None = None,
               data_rejection: DataRejection | None = None) -> dict:
        trace: list[dict] = []
        state = state or {}
        if data_rejection is not None:
            trace.append({"agent": "data", "usable": False, "primary": None,
                          "reasons": [data_rejection.reason]})
            return self._finish(REFUSE, data_rejection.reason, trace, None, None,
                                {"kind": "data", "missing": list(data_rejection.missing)},
                                current_operation=current_operation)

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
        outcome = self._search(budget, confirmed, initial_tanks, current_operation)
        trace.append({"agent": "optimizer", "rounds": outcome.rounds, "max_rounds": self.max_rounds,
                      "evaluated": outcome.evaluated, "evaluation_budget": budget,
                      "note": "Бюджет поиска общий; финальная проверка выбранного плана выполняется отдельно."})
        if outcome.selected is None or outcome.selected.get("selected") is None:
            reasons = sorted({r for e in (outcome.last_result or {}).get("rejected", [])
                              for r in e["rejection_reasons"]})[:5]
            return self._finish(REFUSE,
                                "Ни один вариант не проходит одновременно все обязательные проверки",
                                trace, None, None,
                                {"kind": "no_feasible_plan", "examples": reasons},
                                current_operation=current_operation)
        return self.release(outcome.selected, outcome.selected_plan, outcome.feasible, outcome.by_id, trace,
                            confirmed=confirmed, budget=budget, raw_scenario=raw_scenario,
                            initial_tanks=initial_tanks, current_operation=current_operation)

    def _search(self, budget: int, confirmed=(), initial_tanks=None, current_operation=None) -> "SearchOutcome":
        """The bounded proposal/veto loop. Returns what was examined and, if any, the ranked choice."""
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
                examined.append(evaluation)
                examined_by_id[plan.plan_id] = plan
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
            last_result = rank(feasible or evaluations, hold_id="hold", min_useful_gain=self._min_useful_gain())
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
        return SearchOutcome(selected=selected, selected_plan=selected_plan_obj, feasible=feasible, by_id=by_id,
                             rounds=rounds, evaluated=evaluated_total, last_result=last_result,
                             examined=examined, examined_by_id=examined_by_id, seen_content=seen_content,
                             forbidden=frozenset(forbidden))

    def release(self, selected: dict, selected_plan_obj, feasible, by_id, trace: list[dict], *, confirmed=(),
                budget: int = 600, raw_scenario: dict | None = None, initial_tanks=None,
                current_operation: dict | None = None) -> dict:
        """Look past the horizon, re-check the chosen plan through the gate, test robustness, finish.

        Shared by every path that releases a decision, so no path can skip the final checks.
        """
        # 2b. Look past the horizon: a plan that is fine for three hours may still run the stored
        #     product out of spec before anyone can react. This never waives a gate check.
        lookahead = None
        try:
            lookahead, selected, selected_plan_obj = self._look_ahead(
                selected, selected_plan_obj, feasible, by_id, confirmed, initial_tanks, current_operation)
        except (PlannerError, ValueError) as exc:
            lookahead = {"available": False, "reason": f"Расчёт за горизонтом не выполнен: {exc}"}
        if lookahead is not None:
            trace.append({"agent": "lookahead", **{k: v for k, v in lookahead.items() if k != "alternatives"}})

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

        # 3b. Weak edge of the data-driven response: a plan that moves the reactor-inlet temperature
        #     must also pass the gate with the slope as weak as the study allows for the next half-year.
        #     A plan that fails there is vetoed, not merely called fragile; the remaining feasible plans
        #     are ranked again. Holds and plans without a temperature move are not affected.
        guard = self._weak_response_guard(chosen, confirmed, raw_scenario, initial_tanks, current_operation, lookahead)
        if guard is not None:
            trace.append({"agent": "response_guard", "stage": "final", **guard})
            if guard["outcome"] == "violated":
                vetoed = chosen.plan_id
                remaining = [e for e in feasible if e.candidate.candidate_id != vetoed]
                remaining_by_id = {k: v for k, v in by_id.items() if k != vetoed}
                ranked = rank(remaining, hold_id="hold", min_useful_gain=self._min_useful_gain()) if remaining else None
                if ranked is not None and ranked.get("selected") is not None:
                    next_id = ranked["selected"]["candidate_id"]
                    return self.release(ranked, remaining_by_id.get(next_id), remaining, remaining_by_id, trace,
                                        confirmed=confirmed, budget=budget, raw_scenario=raw_scenario,
                                        initial_tanks=initial_tanks, current_operation=current_operation)
                return self._finish(REFUSE,
                                    "Ход температуры не выдерживает слабый край отклика по данным, других "
                                    "допустимых планов нет: решение не выдаётся",
                                    trace, None, None,
                                    {"kind": "weak_response_failed", "plan_id": vetoed,
                                     "examples": list(guard.get("violations", ()))[:5]},
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
        warning = (lookahead or {}).get("warning")
        if warning:
            reason += f". {warning}"
        if robustness is not None and robustness["fragile"]:
            reason += (f". Предупреждение: план теряет допустимость при "
                       f"{robustness['violated']} из {robustness['perturbations_evaluated']} "
                       f"заданных отклонений и надёжным не считается")
        return self._finish(
            status, reason, trace, chosen, final, None, selected, robustness,
            current_operation=current_operation, lookahead=lookahead,
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
                           current_operation=command.current_operation,
                           data_rejection=command.data_rejection)

    def _min_useful_gain(self) -> float:
        return float(self.scenario.policy.get("min_useful_gain", 0.0))

    def _weak_response_guard(self, plan, confirmed, raw_scenario, initial_tanks, current_operation,
                             lookahead: dict | None = None) -> dict | None:
        """Gate verdict for `plan` with the data-driven slope at its weak edge (`weak_strong[0]`).

        The gate runs over the case horizon and, when the look-ahead is on, over the same extended horizon:
        a temperature move justified by pushing a violation past the reaction window must still do so at the
        weak edge. None when there is nothing to check: no raw scenario, no parser, or the slope is not from data.
        """
        parser = getattr(self.robustness_evaluator, "scenario_parser", None)
        if raw_scenario is None or parser is None:
            return None
        weak = weak_response_raw(raw_scenario)
        if weak is None:
            return None
        model = raw_scenario["stages"]["hydrotreating"]["model"]
        entry = {"plan": plan.plan_id, "beta": model["beta_mgkg_per_c"], "beta_weak": model["weak_strong"][0]}
        pending = self.planner.confirmed_with_operation(confirmed, current_operation)
        if not moves_temperature(plan, self.planner.base_controls(), pending):
            return {**entry, "outcome": "not_applicable",
                    "reason": "план не меняет температуру входа реактора: слабый край отклика на него не действует"}
        try:
            planner = PlanOperation(parser(weak))
            evaluation = planner.evaluate(plan, confirmed, initial_tanks=initial_tanks, current_operation=current_operation)
        except (PlannerError, ValueError) as exc:
            return {**entry, "outcome": "violated",
                    "violations": [f"Проверка при слабом крае отклика не выполнена: {exc}"]}
        if not evaluation.feasible or not self._review_passes(self._review(evaluation)):
            return {**entry, "outcome": "violated", "violations": list(evaluation.gate.rejection_reasons())[:5]}
        if lookahead and lookahead.get("available"):
            hours, window = lookahead["lookahead_hours"], lookahead["min_reaction_hours"]
            nominal = (lookahead.get("selected") or {}).get("hours_to_violation")
            try:
                weak_look = planner.lookahead(plan, hours, confirmed, initial_tanks, current_operation)
            except (PlannerError, ValueError) as exc:
                return {**entry, "outcome": "violated",
                        "violations": [f"Расчёт за горизонтом при слабом крае отклика не выполнен: {exc}"]}
            weak_hours = weak_look["hours_to_violation"]
            entry.update(lookahead_hours_to_violation=nominal, weak_lookahead_hours_to_violation=weak_hours)
            if weak_hours is not None and weak_hours < window and (nominal is None or nominal >= window):
                name = str(weak_look["constraint"]).split(".", 1)[-1]
                return {**entry, "outcome": "violated",
                        "violations": [f"при слабом крае отклика {name} = {weak_look['observed']:.2f} выйдет за предел "
                                       f"{weak_look['limit']:g} через {weak_hours:g} ч, раньше запаса реакции {window:g} ч"]}
        return {**entry, "outcome": "holds", "violations": []}

    # --- Deterministic building blocks reused by the agent layer ---

    def build_plans(self, budget: int, current_operation: dict | None = None):
        return self._build_plans(budget, current_operation)

    def evaluate_plan(self, plan, confirmed=(), initial_tanks=None, current_operation: dict | None = None):
        return self._evaluate_plan(plan, confirmed, initial_tanks, current_operation)

    def passes_review(self, evaluation) -> bool:
        """Gate feasibility plus the deterministic quality and reliability validators, as in the search."""
        return evaluation.feasible and self._review_passes(self._review(evaluation))

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

    def _look_ahead(self, selected, plan_obj, feasible, by_id, confirmed, initial_tanks, current_operation):
        """Project the chosen plan past the horizon; prefer a feasible plan that leaves time to react."""
        policy = self.scenario.policy or {}
        hours, window = policy.get("lookahead_hours"), policy.get("min_reaction_hours")
        numbers = all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
                      for v in (hours, window))
        if not numbers or hours <= 0 or window <= 0:
            return None, selected, plan_obj
        plan_id = selected["selected"]["candidate_id"]
        plan = plan_obj or by_id[plan_id]
        first = self.planner.lookahead(plan, hours, confirmed, initial_tanks, current_operation)
        result = {"available": True, "lookahead_hours": hours, "min_reaction_hours": window,
                  "initial_plan": plan_id, "initial": first, "selected": first, "switched": False,
                  "examined": 0, "warning": None}
        if first["hours_to_violation"] is None or first["hours_to_violation"] >= window:
            return result, selected, plan
        best_reach, best_eval, best_info = first["hours_to_violation"], None, first
        for evaluation in sorted(feasible, key=lambda e: e.key()):
            candidate_id = evaluation.candidate.candidate_id
            if candidate_id == plan_id or candidate_id not in by_id:
                continue
            if result["examined"] >= LOOKAHEAD_CANDIDATES:
                break
            result["examined"] += 1
            try:
                info = self.planner.lookahead(by_id[candidate_id], hours, confirmed, initial_tanks, current_operation)
            except (PlannerError, ValueError):
                continue
            # A projection that stopped because a stock ran out does not prove the plan holds.
            reach = next((v for v in (info["hours_to_violation"], info["stock_ends_at_hours"]) if v is not None),
                         math.inf)
            if reach > best_reach:
                best_reach, best_eval, best_info = reach, evaluation, info
            if reach >= window:
                break
        what = (f"{first['constraint'].split('.', 1)[1]} = {first['observed']:.2f} при пределе {first['limit']:g}"
                if first["observed"] is not None else first["constraint"])
        if best_eval is not None:
            selected = {**selected, "selected": best_eval.to_dict(),
                        "reason": (f"Упреждение за горизонтом: при плане {plan_id} {what} через "
                                   f"{first['hours_to_violation']:g} ч, раньше запаса реакции {window:g} ч; "
                                   f"выбран допустимый план, отодвигающий нарушение")}
            plan = by_id[best_eval.candidate.candidate_id]
            result.update(selected=best_info, switched=True)
        remaining = result["selected"]["hours_to_violation"]
        stock_ends = result["selected"]["stock_ends_at_hours"]
        if remaining is not None and remaining < window:
            result["warning"] = (f"Предупреждение: при сохранении выбранного плана за горизонтом "
                                 f"{result['selected']['constraint'].split('.', 1)[1]} выйдет за предел через "
                                 f"{remaining:g} ч; допустимого плана с запасом реакции {window:g} ч не найдено")
        elif remaining is None and stock_ends is not None and stock_ends < window:
            result["warning"] = (f"Предупреждение: выбранный план отодвигает нарушение качества, но запас компонента "
                                 f"закончится через {stock_ends:g} ч, раньше запаса реакции {window:g} ч")
        return result, selected, plan

    def _finish(self, status, reason, trace, plan, evaluation, refusal, ranking=None,
                robustness=None, current_operation=None, lookahead=None) -> dict:
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
            "lookahead": lookahead,
            "trace": trace,
            "note": ("Результат сценарный. Выданный план не считается исполненным и не разрешает "
                     "выпуск товарного топлива."),
        }
        content = json.dumps(result, sort_keys=True, ensure_ascii=False, default=str)
        result["decision_id"] = hashlib.sha256(content.encode()).hexdigest()[:16]
        return result
