from typing import Mapping, Protocol


class ResponseEffectProvider(Protocol):
    def effect(self, context: Mapping[str, object], delta_t_c: float) -> Mapping[str, object]:
        ...
