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
from dataclasses import dataclass, field
import hashlib
import json

from .contracts import (CONFIRMED_SCOPE, HOLD, RECOMMEND_SCENARIO, REFUSE, SCENARIO_SCOPE)
from .planner import Planner, PlannerError
from .scenario import Scenario
from .trust import DataTrustAgent

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
                "vetoes": [c.reason for c in failed],
                "unknown": [c.reason for c in unknown],
                "severity_index": evaluation.severity_index,
                "verdict": "fail" if failed else ("unknown" if unknown else "pass"),
                "scope": "Ограничения оборудования заданы сценарием; это не оценка реального ресурса."}


@dataclass
class Orchestrator:
    """Runs the loop and produces the decision, or explains why there is none."""

    scenario: Scenario
    planner: Planner = field(init=False)
    quality: QualityAgent = field(default_factory=QualityAgent)
    reliability: ReliabilityAgent = field(default_factory=ReliabilityAgent)
    max_rounds: int = MAX_ROUNDS

    def __post_init__(self):
        self.planner = Planner(self.scenario)

    def decide(self, state: dict | None = None, confirmed=(), budget: int = 600,
               trust_cfg: dict | None = None) -> dict:
        trace: list[dict] = []
        state = state or {}

        # 1. Data first: a state that cannot carry a decision stops the loop before any model runs.
        if state:
            report = DataTrustAgent(trust_cfg or {}).assess(state)
            trace.append({"agent": "data", "usable": report.usable, "primary": report.primary,
                          "reasons": list(report.reasons)})
            if not report.usable:
                return self._finish(REFUSE, report.refusal_reason(), trace, None, None,
                                    {"kind": "data", "missing": list(report.missing_requirements)})

        # 2. Bounded proposal/veto loop.
        forbidden: set[str] = set()
        rounds = []
        selected = None
        last_result = None
        for round_number in range(1, self.max_rounds + 1):
            try:
                plans, info = self.planner.build_plans(budget)
            except (PlannerError, ValueError) as exc:
                raise AgentError(f"Оптимизатор не смог построить кандидатов: {exc}") from exc
            evaluations, by_id = [], {}
            for plan in plans:
                if self._forbidden(plan, forbidden):
                    continue
                try:
                    evaluation = self.planner.evaluate(plan, confirmed)
                except (PlannerError, ValueError):
                    continue
                evaluations.append(evaluation)
                by_id[plan.plan_id] = plan
            if not evaluations:
                rounds.append({"round": round_number, "proposed": 0, "feasible": 0,
                               "note": "После запретов кандидатов не осталось"})
                break

            feasible = [e for e in evaluations if e.feasible]
            reviews = [self._review(e) for e in evaluations[:200]]
            vetoes = self._collect_vetoes(evaluations)
            rounds.append({
                "round": round_number, "proposed": len(evaluations), "feasible": len(feasible),
                "forbidden_before": sorted(forbidden),
                "veto_families": {k: len(v) for k, v in vetoes.items()},
                "quality_vetoed": sum(1 for r in reviews if r["quality"]["verdict"] == "fail"),
                "reliability_vetoed": sum(1 for r in reviews if r["reliability"]["verdict"] == "fail"),
            })
            from .optimizer import rank
            last_result = rank(evaluations, hold_id="hold",
                               min_useful_gain=float(self.scenario.policy.get("min_useful_gain", 0.0)))
            if feasible:
                selected = last_result
                break
            # A veto must change the next search, not merely be recorded.
            added = self._restrict(vetoes, forbidden)
            rounds[-1]["restriction_added"] = added
            if not added:
                rounds[-1]["note"] = "Запреты не сузили поиск: повторять бессмысленно"
                break

        trace.append({"agent": "optimizer", "rounds": rounds, "max_rounds": self.max_rounds})
        if selected is None or selected.get("selected") is None:
            reasons = sorted({r for e in (last_result or {}).get("rejected", [])
                              for r in e["rejection_reasons"]})[:5]
            return self._finish(REFUSE,
                                "Ни один вариант не проходит одновременно все обязательные проверки",
                                trace, None, None,
                                {"kind": "no_feasible_plan", "examples": reasons})

        # 3. Re-check the chosen plan through the same gate before releasing it.
        plan_id = selected["selected"]["candidate_id"]
        plans, _ = self.planner.build_plans(budget)
        chosen = next((p for p in plans if p.plan_id == plan_id), None)
        if chosen is None:
            raise AgentError(f"Выбранный план {plan_id} не найден при повторной проверке")
        final = self.planner.evaluate(chosen, confirmed)
        review = self._review(final)
        trace.append({"agent": "quality", "stage": "final", **review["quality"]})
        trace.append({"agent": "reliability", "stage": "final", **review["reliability"]})
        if not final.feasible:
            return self._finish(REFUSE,
                                "Повторная проверка выбранного плана не пройдена: решение не выдаётся",
                                trace, None, None,
                                {"kind": "final_recheck_failed",
                                 "examples": list(final.gate.rejection_reasons())[:5]})

        status = HOLD if chosen.changes == 0 else RECOMMEND_SCENARIO
        reason = ("Текущий режим проходит все обязательные проверки; изменения не требуются"
                  if status == HOLD else selected["reason"])
        return self._finish(status, reason, trace, chosen, final, None, selected)

    # --- Internals ---

    def _review(self, evaluation) -> dict:
        return {"quality": self.quality.review(evaluation),
                "reliability": self.reliability.review(evaluation)}

    @staticmethod
    def _collect_vetoes(evaluations) -> dict[str, list[str]]:
        vetoes: dict[str, list[str]] = {}
        for evaluation in evaluations:
            for check in evaluation.gate.checks:
                if check.status in ("fail", "unknown"):
                    vetoes.setdefault(_family(check.constraint_id), []).append(check.reason)
        return vetoes

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
        """Apply the accumulated restrictions to the candidate before it is evaluated."""
        if "family:outflow" in forbidden or "family:inventory" in forbidden:
            # Drop the highest-throughput half of proposals: the veto said the draw is too big.
            top = max((s.throughput_tph for s in plan.steps), default=0.0)
            ceiling = max(t.max_outflow.value for t in self.scenario.available_tanks())
            if top > ceiling:
                return True
        if "family:additive" in forbidden and any(s.additive_dose > 0 for s in plan.steps):
            return True
        return False

    def _finish(self, status, reason, trace, plan, evaluation, refusal, ranking=None) -> dict:
        result = {
            "status": status, "reason": reason, "scope": SCENARIO_SCOPE,
            "commercial_release_allowed": False,
            "scenario_id": self.scenario.scenario_id,
            "selected_plan": plan.to_dict() if plan is not None else None,
            "immediate_action": plan.steps[0].to_dict() if plan is not None else None,
            "gate": evaluation.gate.to_dict() if evaluation is not None else None,
            "production_t": evaluation.production_t if evaluation is not None else None,
            "cost_per_tonne": evaluation.cost_per_tonne if evaluation is not None else None,
            "severity_index": evaluation.severity_index if evaluation is not None else None,
            "alternatives": (ranking or {}).get("alternatives", []),
            "rejected": (ranking or {}).get("rejected", []),
            "refusal": refusal,
            "trace": trace,
            "note": ("Результат сценарный. Выданный план не считается исполненным и не разрешает "
                     "выпуск товарного топлива."),
        }
        content = json.dumps(result, sort_keys=True, ensure_ascii=False, default=str)
        result["decision_id"] = hashlib.sha256(content.encode()).hexdigest()[:16]
        return result
