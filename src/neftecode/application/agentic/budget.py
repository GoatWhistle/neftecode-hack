from dataclasses import dataclass, field
import time
from typing import Callable

from .contracts import AgentSettings


class BudgetExhausted(RuntimeError):

    def __init__(self, what: str):
        super().__init__(f"budget exhausted: {what}")
        self.what = what


@dataclass
class AgentBudget:
    settings: AgentSettings
    clock: Callable[[], float] = time.monotonic
    started: float = field(init=False)
    calls: int = field(init=False, default=0)
    calls_by_role: dict = field(init=False, default_factory=dict)
    replans: int = field(init=False, default=0)
    consults: dict = field(init=False, default_factory=dict)
    robustness_runs: int = field(init=False, default=0)
    usage: dict = field(init=False, default_factory=lambda: {"prompt_tokens": 0, "completion_tokens": 0,
                                                             "total_tokens": 0})

    def __post_init__(self):
        self.started = self.clock()

    def elapsed(self) -> float:
        return self.clock() - self.started

    def check_deadline(self) -> None:
        if self.elapsed() >= self.settings.timeout_s:
            raise BudgetExhausted("timeout")

    def remaining_seconds(self) -> float:
        return max(0.0, self.settings.timeout_s - self.elapsed())

    def take_call(self, role: str) -> None:
        self.check_deadline()
        if self.calls >= self.settings.max_llm_calls:
            raise BudgetExhausted("llm_calls")
        self.calls += 1
        self.calls_by_role[role] = self.calls_by_role.get(role, 0) + 1

    def add_usage(self, usage: dict) -> None:
        for key in self.usage:
            value = usage.get(key, 0)
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                self.usage[key] += value

    def take_replan(self) -> bool:
        if self.replans >= self.settings.max_replans:
            return False
        self.replans += 1
        return True

    def take_consult(self, role: str) -> bool:
        used = self.consults.get(role, 0)
        if used >= self.settings.max_specialist_consults:
            return False
        self.consults[role] = used + 1
        return True

    def take_robustness(self) -> bool:
        if self.robustness_runs >= self.settings.max_robustness_runs:
            return False
        self.robustness_runs += 1
        return True

    def to_dict(self) -> dict:
        return {"llm_calls": self.calls, "llm_calls_by_role": dict(sorted(self.calls_by_role.items())),
                "max_llm_calls": self.settings.max_llm_calls, "replans": self.replans,
                "consults": dict(sorted(self.consults.items())), "robustness_runs": self.robustness_runs,
                "usage": dict(self.usage)}
