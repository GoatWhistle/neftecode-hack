"""Typed messages exchanged by application use cases and their adapters."""
from dataclasses import dataclass
from typing import Mapping, Sequence, TypeAlias

from neftecode.domain.production.state import TankState

DecisionResult: TypeAlias = dict[str, object]
PlanningResult: TypeAlias = dict[str, object]
ReplayResult: TypeAlias = dict[str, object]
LiveAdviceResult: TypeAlias = dict[str, object]


@dataclass(frozen=True)
class DecisionCommand:
    state: Mapping[str, object] | None = None
    confirmed: Sequence[tuple[float, Mapping[str, float]]] = ()
    budget: int = 600
    trust_cfg: Mapping[str, object] | None = None
    raw_scenario: Mapping[str, object] | None = None
    initial_tanks: Mapping[str, TankState] | None = None
    current_operation: Mapping[str, object] | None = None


@dataclass(frozen=True)
class PlanningCommand:
    confirmed: Sequence[tuple[float, Mapping[str, float]]] = ()
    budget: int = 120


@dataclass(frozen=True)
class ReplayCommand:
    moments: Sequence[Mapping[str, object]] = ()
    mode: str = "simulated"
    execution: object | None = None


@dataclass(frozen=True)
class LiveAdviceCommand:
    at: str
