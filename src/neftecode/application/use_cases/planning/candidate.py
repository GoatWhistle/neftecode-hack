from dataclasses import dataclass

from neftecode.domain.advisory.entities import PlanStep


class PlannerError(ValueError):
    pass


@dataclass(frozen=True)
class PlanCandidate:

    plan_id: str
    steps: tuple[PlanStep, ...]
    changes: int = 0
    intent: str = ""

    def immediate(self) -> PlanStep:
        return self.steps[0]

    def to_dict(self) -> dict:
        return {"plan_id": self.plan_id, "intent": self.intent, "changes": self.changes,
                "steps": [s.to_advice_dict() for s in self.steps]}
