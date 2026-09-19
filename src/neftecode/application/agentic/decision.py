from collections.abc import Callable
from dataclasses import dataclass, field
import time

from neftecode.application.contracts import DecisionCommand
from neftecode.application.ports import LLMClient, ResponseEffectProvider, RobustnessEvaluator
from neftecode.application.use_cases.make_decision import MakeDecision
from neftecode.application.use_cases.plan_operation import PlanOperation, PlannerError
from neftecode.domain.production.scenario import Scenario
from neftecode.domain.shared.primitives import HOLD, RECOMMEND_SCENARIO, REFUSE

from .budget import AgentBudget
from .contracts import AgentSettings, OrchestratorFinal
from neftecode.application.progress import emit, emit_agent_event

from .loop import AgentTrace
from .orchestrator import OrchestratorAgent, opinion_summary
from .session import DecisionSession

NOTE = ("LLM-агенты выбирают инструменты и предлагают ограничения; числа, допустимость, ранжирование, "
        "финальная перепроверка и устойчивость — детерминированный код. Сценарный результат.")

DETERMINISTIC_PROVIDERS = ("scripted",)

DETERMINISTIC_LABEL = ("Решение прошло через детерминированную политику, а не через языковую модель: "
                       "шаги в трассе заданы кодом и воспроизводятся побитово. Это не рассуждение модели.")


@dataclass
class AgenticMakeDecision:
    scenario: Scenario
    llm: LLMClient | None
    settings: AgentSettings = field(default_factory=AgentSettings)
    robustness_evaluator: RobustnessEvaluator | None = None
    response_effect: ResponseEffectProvider | None = None
    live_context: dict | None = None
    configuration_error: str | None = None
    provider_description: dict | None = None
    orchestrator: OrchestratorAgent = field(default_factory=OrchestratorAgent)
    clock: Callable[[], float] = time.monotonic
    maker: MakeDecision = field(init=False)

    def __post_init__(self):
        self.maker = MakeDecision(self.scenario, robustness_evaluator=self.robustness_evaluator)
        self.planner = self.maker.planner

    def execute(self, command: DecisionCommand) -> dict:
        if not isinstance(command, DecisionCommand):
            raise TypeError("AgenticMakeDecision.execute expects DecisionCommand")
        state = dict(command.state) if command.state is not None else None
        return self.decide(state=state, confirmed=command.confirmed, budget=command.budget,
                           trust_cfg=command.trust_cfg, raw_scenario=command.raw_scenario,
                           initial_tanks=command.initial_tanks, current_operation=command.current_operation,
                           data_rejection=command.data_rejection)

    def decide(self, state: dict | None = None, confirmed=(), budget: int = 600, trust_cfg: dict | None = None,
               raw_scenario: dict | None = None, initial_tanks=None, current_operation: dict | None = None,
               data_rejection=None) -> dict:
        request = dict(state=state, confirmed=confirmed, budget=budget, trust_cfg=trust_cfg, raw_scenario=raw_scenario,
                       initial_tanks=initial_tanks, current_operation=current_operation, data_rejection=data_rejection)
        legacy = self.maker.decide(**request)
        info = {"mode": "agentic", "outcome": None, "fallback_reason": None,
                "legacy_decision_id": legacy["decision_id"], "legacy_status": legacy["status"],
                "provider": getattr(self.llm, "provider", None) or (self.provider_description or {}).get("provider"),
                "model": getattr(self.llm, "model", None) or (self.provider_description or {}).get("model"),
                "note": NOTE}
        info["deterministic_policy"] = info["provider"] in DETERMINISTIC_PROVIDERS
        if info["deterministic_policy"]:
            info["provider_label"] = DETERMINISTIC_LABEL
        if (legacy.get("refusal") or {}).get("kind") == "data":
            return self._with(legacy, info, "skipped", "data_refusal")
        if self.llm is None:
            return self._with(legacy, info, "fallback", self.configuration_error or "llm_not_configured")
        emit("stage", stage="agents", state="running", provider=info["provider"], model=info["model"],
             deterministic_policy=info["deterministic_policy"], budget_limits=self.settings.to_dict())
        trace = AgentTrace(sink=emit_agent_event)
        agent_budget = AgentBudget(self.settings, clock=self.clock)
        try:
            return self._agentic(legacy, request, info, trace, agent_budget)
        except Exception as exc:
            info.update(trace=trace.to_list(), budget=agent_budget.to_dict())
            return self._with(legacy, info, "fallback", f"unexpected_error:{type(exc).__name__}")


    def _agentic(self, legacy: dict, request: dict, info: dict, trace: AgentTrace, agent_budget: AgentBudget) -> dict:
        outcome = self.maker._search(request["budget"], request["confirmed"], request["initial_tanks"],
                                     request["current_operation"])
        session = DecisionSession(self.maker, outcome, legacy, self.settings, agent_budget,
                                  evaluation_budget=request["budget"], confirmed=tuple(request["confirmed"]),
                                  initial_tanks=request["initial_tanks"], current_operation=request["current_operation"],
                                  raw_scenario=request["raw_scenario"], state=request["state"],
                                  trust_cfg=request["trust_cfg"], live_context=self.live_context,
                                  response_effect=self.response_effect)
        run = self.orchestrator.run(llm=self.llm, session=session, budget=agent_budget, settings=self.settings,
                                    trace=trace)
        info.update(opinions=[opinion_summary(o) for o in run.opinions],
                    constraints_applied=[c.to_dict() for c in session.constraints],
                    vetoed_candidates={cid: sorted(roles) for cid, roles in sorted(session.vetoes.items())},
                    llm_choice_overridden=False)
        if run.final is None:
            info.update(trace=trace.to_list(), budget=agent_budget.to_dict())
            return self._with(legacy, info, "fallback", f"orchestrator_no_final:{run.stop_reason}")
        info["final"] = run.final.to_dict()
        result, outcome_name, reason = self._resolve(run.final, run.opinions, session, legacy, request, info, trace)
        info.update(trace=trace.to_list(), budget=agent_budget.to_dict())
        return self._with(result, info, outcome_name, reason)

    def _resolve(self, final: OrchestratorFinal, opinions, session: DecisionSession, legacy: dict, request: dict,
                 info: dict, trace: AgentTrace) -> tuple[dict, str, str | None]:
        allowed = session.allowed_ids()
        legacy_id = session.legacy_plan_id
        if final.action == "refuse":
            grounded = any(o.valid and (o.verdict == "REJECT" or (o.verdict == "UNKNOWN" and o.risk_level == "high"))
                           for o in opinions)
            if not grounded:
                trace.add("system", 0, "resolution", decision="refuse_ignored", reason_codes=("refuse_without_evidence",))
                return legacy, "fallback", "refuse_without_evidence"
            if legacy["status"] == REFUSE:
                return legacy, "confirmed_legacy", None
            return self._refuse(final, session, legacy, request, trace), "refused", None
        if final.action == "keep_legacy":
            if legacy_id is None or legacy_id in allowed:
                return legacy, "confirmed_legacy", None
            trace.add("system", 0, "resolution", decision="legacy_excluded", candidate_ids=(legacy_id,),
                      reason_codes=("legacy_excluded_by_agents",))
        elif final.action == "select" and final.candidate_id not in allowed:
            trace.add("system", 0, "resolution", decision="selection_not_allowed",
                      candidate_ids=(final.candidate_id,), reason_codes=("selection_not_allowed",))
            return legacy, "fallback", "selection_not_allowed"
        if not allowed:
            return self._refuse(final, session, legacy, request, trace), "refused", None
        ranked = session.rank_allowed()["_result"]
        chosen = ranked["selected"]["candidate_id"]
        if final.action == "select" and final.candidate_id != chosen:
            info["llm_choice_overridden"] = True
            trace.add("system", 0, "resolution", decision="rank_overrides_choice",
                      candidate_ids=(final.candidate_id, chosen), reason_codes=("llm_choice_overridden",))
        if chosen == legacy_id and not session.constraints and not session.vetoes:
            return legacy, "confirmed_legacy", None
        feasible = [session.evaluations[cid] for cid in allowed]
        by_id = {cid: session.plans[cid] for cid in allowed}
        trace_entries = self._core_trace(legacy) + [self._agent_entry(final, session, chosen)]
        result = self.maker.release(ranked, by_id[chosen], feasible, by_id, trace_entries,
                                    confirmed=request["confirmed"], budget=request["budget"],
                                    raw_scenario=request["raw_scenario"], initial_tanks=request["initial_tanks"],
                                    current_operation=request["current_operation"])
        result = self._guard(result, session, request, trace)
        name = "selected" if result["status"] != REFUSE else "refused"
        return result, name, None

    def _guard(self, result: dict, session: DecisionSession, request: dict, trace: AgentTrace) -> dict:
        if result["status"] not in (HOLD, RECOMMEND_SCENARIO):
            return result
        plan_id = result["selected_plan"]["plan_id"]
        plan = session.plans.get(plan_id)
        failure = None
        if plan is None:
            failure = [f"План {plan_id} не найден при повторной проверке"]
        else:
            planner = PlanOperation(self.scenario)
            kwargs = {}
            if request["initial_tanks"] is not None:
                kwargs["initial_tanks"] = request["initial_tanks"]
            if request["current_operation"] is not None:
                kwargs["current_operation"] = request["current_operation"]
            try:
                evaluation = planner.evaluate(plan, request["confirmed"], **kwargs)
                if not evaluation.feasible:
                    failure = list(evaluation.gate.rejection_reasons())[:5]
            except (PlannerError, ValueError) as exc:
                failure = [f"Повторная проверка не выполнена: {exc}"]
        if failure is None:
            trace.add("system", 0, "guard", decision="pass", candidate_ids=(plan_id,))
            return result
        trace.add("system", 0, "guard", decision="fail", candidate_ids=(plan_id,), reason_codes=("guard_failed",))
        core = [entry for entry in result["trace"] if entry.get("agent") in ("data", "optimizer", "agentic")]
        return self.maker._finish(REFUSE, "Повторная проверка выбранного плана не пройдена: решение не выдаётся",
                                  core, None, None, {"kind": "final_recheck_failed", "examples": failure},
                                  current_operation=request["current_operation"])

    def _refuse(self, final: OrchestratorFinal, session: DecisionSession, legacy: dict, request: dict,
                trace: AgentTrace) -> dict:
        trace.add("system", 0, "resolution", decision="refuse", reason_codes=final.reason_codes)
        entries = self._core_trace(legacy) + [self._agent_entry(final, session, None)]
        reason = "Агенты не нашли плана, приемлемого по качеству и эксплуатации среди допустимых: решение не выдаётся"
        return self.maker._finish(REFUSE, reason, entries, None, None,
                                  {"kind": "agent_rejected", "reason_codes": list(final.reason_codes),
                                   "summary": final.summary,
                                   "vetoed": sorted(session.vetoes), "constraints": [c.to_dict() for c in session.constraints]},
                                  current_operation=request["current_operation"])

    @staticmethod
    def _core_trace(legacy: dict) -> list[dict]:
        return [entry for entry in legacy["trace"] if entry.get("agent") in ("data", "optimizer")]

    @staticmethod
    def _agent_entry(final: OrchestratorFinal, session: DecisionSession, chosen: str | None) -> dict:
        return {"agent": "agentic", "action": final.action, "proposed": final.candidate_id, "selected": chosen,
                "reason_codes": list(final.reason_codes), "constraints": [c.to_dict() for c in session.constraints],
                "vetoed": sorted(session.vetoes), "allowed": len(session.allowed_ids()),
                "evaluated": session.evaluated}

    @staticmethod
    def _with(decision: dict, info: dict, outcome: str, reason: str | None) -> dict:
        info = dict(info, outcome=outcome, fallback_reason=reason)
        return {**decision, "agentic": info}
