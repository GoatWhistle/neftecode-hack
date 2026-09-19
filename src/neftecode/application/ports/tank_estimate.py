from typing import Callable, Mapping, Protocol, Sequence


class TankEstimateEvaluator(Protocol):
    def evaluate(self, status: str, plan_id: str | None, budget: int = 200,
                 confirmed: Sequence[tuple[float, Mapping[str, float]]] = (),
                 current_operation: Mapping[str, object] | None = None,
                 initial_tanks: Mapping[str, object] | None = None) -> dict: ...


TankEstimateFactory = Callable[[object, Mapping[str, object], Callable[[dict], object]],
                               TankEstimateEvaluator | None]
