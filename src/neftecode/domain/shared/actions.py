from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from neftecode.domain.shared.primitives import ContractError, PROPOSED, CONFIRMED, EXECUTION_STATUSES, _finite
from neftecode.domain.shared.primitives import _time

@dataclass(frozen=True)
class PendingAction:

    action_id: str
    proposed_at: str
    controls: dict[str, float]
    expected_response_hours: float
    execution_status: str = PROPOSED
    confirmed_at: str | None = None
    observed_response_status: str = "not_evaluated"

    def __post_init__(self):
        object.__setattr__(self, "proposed_at", _time(self.proposed_at, "PendingAction.proposed_at"))
        object.__setattr__(self, "confirmed_at", _time(self.confirmed_at, "PendingAction.confirmed_at", required=False))
        if self.execution_status not in EXECUTION_STATUSES:
            raise ContractError(f"PendingAction.execution_status: ожидается одно из {EXECUTION_STATUSES}")
        if self.execution_status == CONFIRMED and self.confirmed_at is None:
            raise ContractError("PendingAction: подтверждённое действие обязано иметь время подтверждения")
        if self.execution_status != CONFIRMED and self.confirmed_at is not None:
            raise ContractError("PendingAction: время подтверждения без статуса confirmed")
        if not _finite(self.expected_response_hours) or not 0 <= self.expected_response_hours <= 3:
            raise ContractError("PendingAction.expected_response_hours: ожидается 0–3 часа по уточнению эксперта")

    @property
    def executed(self) -> bool:
        return self.execution_status == CONFIRMED

    def effect_expected_at(self) -> str | None:
        if not self.executed:
            return None
        start = datetime.fromisoformat(self.confirmed_at)
        return (start + timedelta(hours=self.expected_response_hours)).isoformat()

    def confirm(self, at) -> "PendingAction":
        if self.executed:
            raise ContractError(f"PendingAction[{self.action_id}]: действие уже подтверждено, повторное подтверждение "
                                f"привело бы к двойному учёту эффекта")
        return replace(self, execution_status=CONFIRMED, confirmed_at=_time(at, "PendingAction.confirm"))

    def to_dict(self) -> dict:
        return {"action_id": self.action_id, "proposed_at": self.proposed_at, "controls": dict(self.controls),
                "expected_response_hours": self.expected_response_hours,
                "execution_status": self.execution_status, "confirmed_at": self.confirmed_at,
                "observed_response_status": self.observed_response_status}

    @classmethod
    def from_dict(cls, raw: dict) -> "PendingAction":
        return cls(raw["action_id"], raw["proposed_at"], dict(raw["controls"]),
                   raw["expected_response_hours"], raw.get("execution_status", PROPOSED),
                   raw.get("confirmed_at"), raw.get("observed_response_status", "not_evaluated"))
