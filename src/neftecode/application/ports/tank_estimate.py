from typing import Callable, Mapping, Protocol, Sequence

from neftecode.domain.advisory.optimizer import DEFAULT_BUDGET


class TankEstimateEvaluator(Protocol):
    def evaluate(self, status: str, plan_id: str | None, budget: int = DEFAULT_BUDGET,
                 confirmed: Sequence[tuple[float, Mapping[str, float]]] = (),
                 current_operation: Mapping[str, object] | None = None,
                 initial_tanks: Mapping[str, object] | None = None) -> dict: ...


TankEstimateFactory = Callable[[object, Mapping[str, object], Callable[[dict], object]],
                               TankEstimateEvaluator | None]
