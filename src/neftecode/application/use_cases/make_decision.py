from collections.abc import Callable
from dataclasses import dataclass, field

from neftecode.domain.shared.primitives import (HOLD, RECOMMEND_SCENARIO, REFUSE)
from .plan_operation import PlanOperation, PlannerError
from neftecode.domain.advisory.optimizer import DEFAULT_BUDGET, rank
from neftecode.domain.advisory.response_guard import moves_temperature, weak_response_raw
from neftecode.domain.production.scenario import Scenario
from neftecode.application.contracts import DataRejection, DecisionCommand, DecisionResult
from neftecode.application.cancellation import check_cancelled
from neftecode.application.ports import RobustnessEvaluator, TankEstimateEvaluator
from neftecode.application.ports.tank_estimate import TankEstimateFactory
from ..progress import emit
from ..services.trust import DataTrustAgent
from .decision.reviews import QualityReview, ReliabilityReview
from .decision.constants import LOOKAHEAD_CANDIDATES, MAX_ROUNDS, VETO_FAMILIES, AgentError, SearchOutcome
from .decision.choice import ChoiceMixin
from .decision.consequences import ConsequencesMixin
from .decision.lookahead import LookaheadMixin
from .decision.search import SearchMixin

__all__ = ["AgentError", "LOOKAHEAD_CANDIDATES", "MAX_ROUNDS", "MakeDecision", "QualityReview",
           "ReliabilityReview", "SearchOutcome", "VETO_FAMILIES"]


@dataclass
class MakeDecision(SearchMixin, LookaheadMixin, ConsequencesMixin, ChoiceMixin):

    scenario: Scenario
    planner: PlanOperation = field(init=False)
    quality: QualityReview = field(default_factory=QualityReview)
    reliability: ReliabilityReview = field(default_factory=ReliabilityReview)
    max_rounds: int = MAX_ROUNDS
    robustness_evaluator: RobustnessEvaluator | None = None
    tank_estimate_evaluator: TankEstimateEvaluator | None = None
    tank_estimate_factory: TankEstimateFactory | None = None
    scenario_parser: Callable[[dict], Scenario] | None = None

    def __post_init__(self):
        self.planner = PlanOperation(self.scenario)

    def decide(self, state: dict | None = None, confirmed=(), budget: int = DEFAULT_BUDGET,
               trust_cfg: dict | None = None, raw_scenario: dict | None = None,
               initial_tanks=None, current_operation: dict | None = None,
               data_rejection: DataRejection | None = None) -> dict:
        check_cancelled()
        trace: list[dict] = []
        state = state or {}
        if data_rejection is not None:
            trace.append({"agent": "data", "usable": False, "primary": None,
                          "reasons": [data_rejection.reason]})
            return self._finish(REFUSE, data_rejection.reason, trace, None, None,
                                {"kind": "data", "missing": list(data_rejection.missing)},
                                current_operation=current_operation)

        if state:
            report = DataTrustAgent(trust_cfg or {}).assess(state)
            trace.append({"agent": "data", "usable": report.usable, "primary": report.primary,
                          "reasons": list(report.reasons), "report": report.to_dict()})
            emit("stage", stage="trust", state="done", usable=report.usable, primary=report.primary)
            if not report.usable:
                return self._finish(REFUSE, report.refusal_reason(), trace, None, None,
                                    {"kind": "data", "missing": list(report.missing_requirements)},
                                    current_operation=current_operation)

        emit("stage", stage="candidates", state="running")
        check_cancelled()
        outcome = self._search(budget, confirmed, initial_tanks, current_operation)
        emit("stage", stage="candidates", state="done", evaluated=outcome.evaluated,
             rounds=len(outcome.rounds), feasible=len(outcome.feasible))
        trace.append({"agent": "optimizer", "rounds": outcome.rounds, "max_rounds": self.max_rounds,
                      "evaluated": outcome.evaluated, "evaluation_budget": budget,
                      "note": "Бюджет поиска общий; финальная проверка выбранного плана выполняется отдельно."})
        if outcome.selected is None or outcome.selected.get("selected") is None:
            if not outcome.examined and outcome.computation_errors:
                errors = sorted({e["error"] for e in outcome.computation_errors})[:5]
                return self._finish(REFUSE,
                                    "Расчёт кандидатов завершился ошибкой во всех попытках; "
                                    "допустимость плана не проверена",
                                    trace, None, None,
                                    {"kind": "computation_error", "examples": errors},
                                    current_operation=current_operation)
            reasons = sorted({r for e in (outcome.last_result or {}).get("rejected", [])
                              for r in e["rejection_reasons"]})[:5]
            return self._finish(REFUSE,
                                "Ни один вариант не проходит одновременно все обязательные проверки",
                                trace, None, None,
                                {"kind": "no_feasible_plan", "examples": reasons},
                                ranking=outcome.last_result,
                                current_operation=current_operation, examined=outcome.examined)
        return self.release(outcome.selected, outcome.selected_plan, outcome.feasible, outcome.by_id, trace,
                            confirmed=confirmed, budget=budget, raw_scenario=raw_scenario,
                            initial_tanks=initial_tanks, current_operation=current_operation,
                            examined=outcome.examined)

    def release(self, selected: dict, selected_plan_obj, feasible, by_id, trace: list[dict], *, confirmed=(),
                budget: int = DEFAULT_BUDGET, raw_scenario: dict | None = None, initial_tanks=None,
                current_operation: dict | None = None, examined=None, vetoed=()) -> dict:
        check_cancelled()
        examined = list(examined) if examined is not None else list(feasible)
        lookahead = None
        emit("stage", stage="forecast", state="running")
        try:
            lookahead, selected, selected_plan_obj = self._look_ahead(
                selected, selected_plan_obj, feasible, by_id, confirmed, initial_tanks, current_operation)
        except (PlannerError, ValueError) as exc:
            lookahead = {"available": False, "reason": f"Расчёт за горизонтом не выполнен: {exc}"}
        if lookahead is not None:
            trace.append({"agent": "lookahead", **{k: v for k, v in lookahead.items() if k != "alternatives"}})
        horizon = (lookahead or {}).get("selected") or {}
        emit("stage", stage="forecast", state="done", available=(lookahead or {}).get("available"),
             lookahead_hours=(lookahead or {}).get("lookahead_hours"),
             min_reaction_hours=(lookahead or {}).get("min_reaction_hours"),
             hours_to_violation=horizon.get("hours_to_violation"),
             stock_ends_at_hours=horizon.get("stock_ends_at_hours"),
             switched=(lookahead or {}).get("switched"),
             examined=(lookahead or {}).get("examined"))

        plan_id = selected["selected"]["candidate_id"]
        emit("stage", stage="choice", state="done", plan_id=plan_id,
             alternatives=len(selected.get("alternatives") or []))
        plans, _ = self._build_plans(budget, current_operation)
        chosen = selected_plan_obj or next((p for p in plans if p.plan_id == plan_id), None)
        if chosen is None:
            raise AgentError(f"Выбранный план {plan_id} не найден при повторной проверке")
        final = self._evaluate_plan(chosen, confirmed, initial_tanks, current_operation)
        review = self._review(final)
        trace.append({"agent": "quality", "stage": "final", **review["quality"]})
        trace.append({"agent": "reliability", "stage": "final", **review["reliability"]})
        emit("stage", stage="gate", state="done", feasible=final.feasible,
             checks=len(final.gate.checks), plan_id=plan_id)
        if not final.feasible or not self._review_passes(review):
            return self._finish(REFUSE,
                                "Повторная проверка выбранного плана не пройдена: решение не выдаётся",
                                trace, None, None,
                                {"kind": "final_recheck_failed",
                                 "examples": list(final.gate.rejection_reasons())[:5]},
                                current_operation=current_operation, examined=examined, vetoed=vetoed)

        guard = self._weak_response_guard(chosen, confirmed, raw_scenario, initial_tanks, current_operation, lookahead)
        if guard is not None:
            trace.append({"agent": "response_guard", "stage": "final", **guard})
            if guard["outcome"] == "violated":
                vetoed_id = chosen.plan_id
                vetoed = (*vetoed, {"candidate_id": vetoed_id, "reason": {
                    "category": "final_veto", "stage": "response_guard",
                    "text": "Не выдерживает слабый край отклика по данным (финальная проверка)",
                    "rule": {"id": "weak_response", "value": guard.get("beta_weak"), "observed": guard.get("beta"),
                             "source": "stages.hydrotreating.model.weak_strong"},
                    "events": list(guard.get("violations", ()))[:5]}})
                remaining = [e for e in feasible if e.candidate.candidate_id != vetoed_id]
                remaining_by_id = {k: v for k, v in by_id.items() if k != vetoed_id}
                ranked = rank(remaining, hold_id="hold", min_useful_gain=self._min_useful_gain(),
                              severity_cost_tolerance_fraction=self._severity_cost_tolerance(),
                              max_severity_index=self._max_severity_index()) if remaining else None
                if ranked is not None and ranked.get("selected") is not None:
                    next_id = ranked["selected"]["candidate_id"]
                    return self.release(ranked, remaining_by_id.get(next_id), remaining, remaining_by_id, trace,
                                        confirmed=confirmed, budget=budget, raw_scenario=raw_scenario,
                                        initial_tanks=initial_tanks, current_operation=current_operation,
                                        examined=examined, vetoed=vetoed)
                return self._finish(REFUSE,
                                    "Ход температуры не выдерживает слабый край отклика по данным, других "
                                    "допустимых планов нет: решение не выдаётся",
                                    trace, None, None,
                                    {"kind": "weak_response_failed", "plan_id": vetoed_id,
                                     "examples": list(guard.get("violations", ()))[:5]},
                                    current_operation=current_operation, examined=examined, vetoed=vetoed)

        robustness = None
        if raw_scenario is not None and self.robustness_evaluator is not None:
            robustness = self.robustness_evaluator.evaluate(
                self.scenario, raw_scenario, chosen, confirmed, initial_tanks, current_operation)
            trace.append({"agent": "robustness", "held": robustness["held"],
                          "evaluated": robustness["perturbations_evaluated"],
                          "not_applicable": robustness.get("not_applicable", 0),
                          "fragile": robustness["fragile"],
                          "mandatory_failed": robustness.get("mandatory_failed", 0)})
            if robustness.get("mandatory_failed", 0):
                vetoed_id = chosen.plan_id
                vetoed = (*vetoed, {"candidate_id": vetoed_id, "reason": {
                    "category": "final_veto", "stage": "robustness",
                    "text": "Не выдерживает обязательный диапазон устойчивости (финальная проверка)",
                    "rule": {"id": "mandatory_robustness", "value": None,
                             "observed": robustness.get("mandatory_failed"), "source": "robustness.mandatory"},
                    "events": list(robustness.get("mandatory_failure_names", ()))[:5]}})
                remaining = [e for e in feasible if e.candidate.candidate_id != vetoed_id]
                remaining_by_id = {k: v for k, v in by_id.items() if k != vetoed_id}
                ranked = rank(remaining, hold_id="hold", min_useful_gain=self._min_useful_gain(),
                              severity_cost_tolerance_fraction=self._severity_cost_tolerance(),
                              max_severity_index=self._max_severity_index()) if remaining else None
                if ranked is not None and ranked.get("selected") is not None:
                    next_id = ranked["selected"]["candidate_id"]
                    return self.release(ranked, remaining_by_id.get(next_id), remaining, remaining_by_id, trace,
                                        confirmed=confirmed, budget=budget, raw_scenario=raw_scenario,
                                        initial_tanks=initial_tanks, current_operation=current_operation,
                                        examined=examined, vetoed=vetoed)
                return self._finish(
                    REFUSE,
                    "Ни один допустимый план не выдерживает обязательный диапазон устойчивости: решение не выдаётся",
                    trace, None, None,
                    {"kind": "mandatory_robustness_failed", "plan_id": vetoed_id,
                     "examples": list(robustness.get("mandatory_failure_names", ()))[:5]},
                    current_operation=current_operation, examined=examined, vetoed=vetoed,
                )

        status = HOLD if chosen.changes == 0 else RECOMMEND_SCENARIO
        tank_estimate = self._tank_estimate(raw_scenario, status, chosen.plan_id, budget, confirmed,
                                            current_operation, initial_tanks)
        if tank_estimate is not None:
            trace.append({"agent": "tank_estimate", "available": tank_estimate["available"],
                          "sensitive": tank_estimate.get("sensitive"),
                          "changed": tank_estimate.get("changed"),
                          "evaluated": tank_estimate.get("perturbations_evaluated")})
        if (tank_estimate or {}).get("mode") == "park_phase" and tank_estimate.get("sensitive"):
            verdict = tank_estimate["verdict"]
            return self._finish(
                REFUSE, verdict, trace, None, final,
                {"kind": "tank_phase_sensitive", "examples": [verdict],
                 "failed_taus_h": list(tank_estimate.get("failed_taus_h") or ())},
                ranking=selected, current_operation=current_operation, lookahead=lookahead,
                tank_estimate=tank_estimate, pool=feasible, examined=examined, vetoed=vetoed,
            )
        reason = ("Текущий режим проходит все обязательные проверки; изменения не требуются"
                  if status == HOLD else selected["reason"])
        warning = (lookahead or {}).get("warning")
        if warning:
            reason += f". {warning}"
        if robustness is not None and robustness["fragile"]:
            reason += (f". Предупреждение: план теряет допустимость при "
                       f"{robustness['violated']} из {robustness['perturbations_evaluated']} "
                       f"заданных отклонений и надёжным не считается")
        if tank_estimate is not None and tank_estimate.get("sensitive"):
            reason += f". {tank_estimate['verdict']}"
        consequences = self._consequences(chosen, final, feasible, by_id, confirmed, current_operation)
        return self._finish(
            status, reason, trace, chosen, final, None, selected, robustness,
            current_operation=current_operation, lookahead=lookahead, tank_estimate=tank_estimate,
            pool=feasible, consequences=consequences, examined=examined, vetoed=vetoed,
        )

    def execute(self, command: DecisionCommand) -> DecisionResult:
        if not isinstance(command, DecisionCommand):
            raise TypeError("MakeDecision.execute expects DecisionCommand")
        state = dict(command.state) if command.state is not None else None
        return self.decide(state=state, confirmed=command.confirmed,
                           budget=command.budget, trust_cfg=command.trust_cfg,
                           raw_scenario=command.raw_scenario,
                           initial_tanks=command.initial_tanks,
                           current_operation=command.current_operation,
                           data_rejection=command.data_rejection)

    def _tank_estimate(self, raw_scenario, status, plan_id, budget, confirmed,
                       current_operation, initial_tanks) -> dict | None:
        evaluator = self.tank_estimate_evaluator
        if evaluator is None:
            factory = self.tank_estimate_factory
            parser = self.scenario_parser
            if factory is None or parser is None or raw_scenario is None:
                return None
            evaluator = factory(self.scenario, raw_scenario, parser)
        if evaluator is None:
            return None
        try:
            return evaluator.evaluate(status, plan_id, budget, confirmed, current_operation,
                                      initial_tanks)
        except (PlannerError, ValueError, KeyError) as exc:
            return {"available": False, "sensitive": False, "tank_id": "main",
                    "reason": f"Проверка чувствительности к оценке резервуара не выполнена: {exc}"}

    def _min_useful_gain(self) -> float:
        return float(self.scenario.policy.get("min_useful_gain", 0.0))

    def _severity_cost_tolerance(self) -> float:
        return float(self.scenario.policy.get("severity_cost_tolerance_fraction", 0.0))

    def _max_severity_index(self) -> float | None:
        value = self.scenario.policy.get("max_severity_index")
        return None if value is None else float(value)

    def _weak_response_guard(self, plan, confirmed, raw_scenario, initial_tanks, current_operation,
                             lookahead: dict | None = None) -> dict | None:
        parser = self.scenario_parser
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

    def build_plans(self, budget: int, current_operation: dict | None = None):
        return self._build_plans(budget, current_operation)

    def evaluate_plan(self, plan, confirmed=(), initial_tanks=None, current_operation: dict | None = None):
        return self._evaluate_plan(plan, confirmed, initial_tanks, current_operation)

    def passes_review(self, evaluation) -> bool:
        return evaluation.feasible and self._review_passes(self._review(evaluation))

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
