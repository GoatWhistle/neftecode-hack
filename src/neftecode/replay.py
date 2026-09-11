"""Replaying decisions: the same core, on history and in the scenario environment.

Two modes, deliberately not mixed in the output:

* **historical** — the decision core runs at a past moment using only what was available then.
  The future laboratory value exists, but it goes to the evaluator *after* the decision and
  never into the state the agents see.
* **simulated** — actions are applied through a separate execution state with its own material
  balance. This is where an alternative control can be studied at all, because history contains
  no observation of what an unexecuted action would have produced.

Because of that split, a historical replay must never be continued as though a recommendation
had been carried out. The history is the history: it already contains whatever the operator
actually did, and nothing else.
"""
from dataclasses import dataclass, field, replace
import hashlib
import json

from .contracts import ContractError, PendingAction, TankState
from .inventory import initial_state
from .orchestrator import Orchestrator
from .scenario import Scenario

HISTORICAL = "historical"
SIMULATED = "simulated"
MODES = (HISTORICAL, SIMULATED)


class ReplayError(ValueError):
    """Raised when a replay is asked to mix history with unexecuted actions."""


@dataclass
class ExecutionState:
    """What the simulated plant actually holds and what has actually been executed.

    Kept apart from the advisor's state so that issuing advice cannot change the plant, and
    so that a pause and a resume lose neither inventory nor a pending action.
    """

    tanks: dict[str, TankState]
    executed: tuple[PendingAction, ...] = ()
    clock_hours: float = 0.0

    @classmethod
    def from_scenario(cls, scenario: Scenario) -> "ExecutionState":
        return cls(initial_state(scenario))

    def confirm(self, action: PendingAction, at) -> "ExecutionState":
        """Record an operator confirmation. Only confirmed actions reach the plant."""
        if any(a.action_id == action.action_id for a in self.executed):
            raise ReplayError(f"Действие {action.action_id} уже исполнено: повторное применение "
                              f"привело бы к двойному учёту")
        return replace(self, executed=self.executed + (action.confirm(at),))

    def draw(self, drawn: dict[str, float]) -> "ExecutionState":
        tanks = dict(self.tanks)
        for tank_id, mass in drawn.items():
            if mass <= 0:
                continue
            tanks[tank_id] = tanks[tank_id].draw(mass)
        return replace(self, tanks=tanks)

    def advance(self, hours: float) -> "ExecutionState":
        return replace(self, clock_hours=self.clock_hours + hours)

    def confirmed_controls(self) -> tuple:
        """Confirmed actions in the form the planner consumes."""
        return tuple((0.0, dict(a.controls)) for a in self.executed)

    def to_dict(self) -> dict:
        return {"clock_hours": self.clock_hours,
                "tanks": {k: v.to_dict() for k, v in self.tanks.items()},
                "executed": [a.to_dict() for a in self.executed]}

    @classmethod
    def from_dict(cls, raw: dict) -> "ExecutionState":
        return cls({k: TankState.from_dict(v) for k, v in raw["tanks"].items()},
                   tuple(PendingAction.from_dict(a) for a in raw.get("executed", ())),
                   raw.get("clock_hours", 0.0))


def versions(scenario: Scenario, raw_scenario: dict | None = None) -> dict:
    """Fingerprint of everything a replay depended on, so a rerun can be compared."""
    payload = json.dumps(raw_scenario if raw_scenario is not None else scenario.to_dict(),
                         sort_keys=True, ensure_ascii=False)
    return {"scenario_id": scenario.scenario_id,
            "scenario_fingerprint": hashlib.sha256(payload.encode()).hexdigest()[:16],
            "horizon_hours": scenario.horizon.hours,
            "models": {"avt": scenario.stages["avt"].model.get("kind"),
                       "hydrotreating": scenario.stages["hydrotreating"].model.get("kind")}}


@dataclass
class Replay:
    """Runs the same decision core in either mode and records what it depended on."""

    scenario: Scenario
    raw_scenario: dict | None = None
    budget: int = 400
    orchestrator: Orchestrator = field(init=False)

    def __post_init__(self):
        self.orchestrator = Orchestrator(self.scenario)

    def step(self, mode: str, state: dict | None = None, execution: ExecutionState | None = None,
             future_truth: dict | None = None) -> dict:
        """One decision. `future_truth` is returned for evaluation and never shown to the agents."""
        if mode not in MODES:
            raise ReplayError(f"Неизвестный режим воспроизведения: {mode}")
        if mode == HISTORICAL and execution is not None and execution.executed:
            raise ReplayError("Историческое воспроизведение не может продолжаться так, будто "
                              "рекомендация была исполнена: история уже содержит действия оператора")
        confirmed = execution.confirmed_controls() if execution is not None else ()
        decision = self.orchestrator.decide(state=state, confirmed=confirmed, budget=self.budget,
                                            raw_scenario=self.raw_scenario)
        return {
            "mode": mode,
            "decision": decision,
            "versions": versions(self.scenario, self.raw_scenario),
            # The evaluator gets the truth; the agents never saw it.
            "evaluation_only": dict(future_truth or {}),
            "note": ("Историческое решение и модельное исполнение разделены: история не "
                     "показывает, что произошло бы после неисполненного действия."
                     if mode == HISTORICAL else
                     "Модельное исполнение. Числа получены в сценарной среде, а не на заводе."),
        }

    def run(self, moments, mode: str = SIMULATED, execution: ExecutionState | None = None) -> dict:
        """Replay a list of moments. Returns each decision plus the final execution state."""
        state = execution or (ExecutionState.from_scenario(self.scenario)
                              if mode == SIMULATED else None)
        records = []
        for moment in moments:
            record = self.step(mode, state=moment.get("state"), execution=state,
                               future_truth=moment.get("future_truth"))
            records.append({"at": moment.get("at"), **record})
            if mode == SIMULATED and state is not None:
                state = self._apply(state, moment, record["decision"])
        return {"mode": mode, "records": records,
                "final_execution": state.to_dict() if state is not None else None,
                "separation": "Результаты истории и моделирования не смешиваются: режим указан "
                              "у каждой записи."}

    def _apply(self, state: ExecutionState, moment: dict, decision: dict) -> ExecutionState:
        """Apply only what the operator confirmed in this moment, never the advice itself."""
        confirmation = moment.get("confirm")
        if not confirmation:
            return state
        action = PendingAction(confirmation["action_id"], confirmation["proposed_at"],
                               dict(confirmation["controls"]),
                               confirmation.get("expected_response_hours", 2.0))
        return state.confirm(action, confirmation["confirmed_at"])


def compare_runs(first: dict, second: dict) -> dict:
    """Are two replays numerically the same decision by decision?"""
    same = []
    for a, b in zip(first["records"], second["records"]):
        same.append({
            "at": a.get("at"),
            "same_status": a["decision"]["status"] == b["decision"]["status"],
            "same_decision_id": a["decision"]["decision_id"] == b["decision"]["decision_id"],
        })
    return {"n": len(same), "identical": all(r["same_decision_id"] for r in same), "per_moment": same}
