"""Agent speech with a mandatory evidence citation. Uncited statements are rejected."""
from dataclasses import asdict, dataclass, field
import math


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


@dataclass(frozen=True)
class Citation:
    """A pointer a person can re-open: a measurement, a model result or a scenario input."""

    kind: str
    ref: str
    time: str | None = None
    value: float | None = None
    detail: str | None = None

    KINDS = ("measurement", "model", "scenario", "history", "config")

    def __post_init__(self):
        if self.kind not in self.KINDS:
            raise ValueError(f"Неизвестный вид ссылки: {self.kind}")
        if not isinstance(self.ref, str) or not self.ref.strip():
            raise ValueError("Ссылка обязана называть тег, модель или параметр сценария")
        if self.value is not None and not _finite(self.value):
            object.__setattr__(self, "value", None)
        if self.time is None and self.value is None and not self.detail:
            raise ValueError(f"Ссылка на {self.ref} пуста: нужно время, значение или пояснение")


@dataclass(frozen=True)
class Claim:
    agent: str
    statement: str
    evidence: tuple[Citation, ...]
    kind: str = "assessment"

    def __post_init__(self):
        if not isinstance(self.statement, str) or not self.statement.strip():
            raise ValueError("Пустое утверждение агента")
        if not self.evidence:
            raise ValueError(f"{self.agent}: утверждение без ссылки на данные запрещено")

    def to_dict(self) -> dict:
        return {"agent": self.agent, "kind": self.kind, "statement": self.statement,
                "evidence": [asdict(c) for c in self.evidence]}


@dataclass
class Ledger:
    """The orchestrator's record. Rejected statements stay visible instead of disappearing."""

    accepted: list[Claim] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)

    def say(self, agent: str, statement: str, evidence, kind: str = "assessment") -> Claim | None:
        try:
            claim = Claim(agent, statement, tuple(evidence or ()), kind)
        except ValueError as exc:
            self.rejected.append({"agent": agent, "statement": statement, "reason": str(exc)})
            return None
        self.accepted.append(claim)
        return claim

    def by_agent(self, agent: str) -> list[Claim]:
        return [c for c in self.accepted if c.agent == agent]

    def to_dict(self) -> dict:
        return {
            "accepted": [c.to_dict() for c in self.accepted],
            "rejected": list(self.rejected),
            "agents": sorted({c.agent for c in self.accepted}),
            "rule": "Каждое принятое утверждение несет ссылку на измерение, модель или параметр сценария. "
                    "Утверждения без ссылки отклонены координатором и перечислены отдельно.",
        }


def measurement(tag: str, time, value, detail: str | None = None) -> Citation:
    return Citation("measurement", tag, None if time is None else str(time),
                    value if _finite(value) else None, detail)


def model_result(name: str, metric: str, value=None, detail: str | None = None) -> Citation:
    return Citation("model", name, None, value if _finite(value) else None,
                    detail or f"показатель: {metric}")


def scenario_input(key: str, value=None, detail: str | None = None) -> Citation:
    return Citation("scenario", key, None, value if _finite(value) else None,
                    detail or "значение задано в конфигурации сценария, не измерено")
