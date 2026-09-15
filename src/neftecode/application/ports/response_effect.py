"""Boundary for the data-derived hydrotreating temperature response.

The response layer S = F(state) + beta_tau * delta_T is specified in RESPONSE_MODEL_FINAL.md but is not
integrated: the meaning of the tags it rests on (T11, F26) awaits the organisers. Agents may ask for the
effect; until an adapter is wired the answer says plainly that it is unavailable.
"""
from typing import Mapping, Protocol


class ResponseEffectProvider(Protocol):
    def effect(self, context: Mapping[str, object], delta_t_c: float) -> Mapping[str, object]:
        """Return at least `available: bool` and `reason: str`; numbers only when available."""
        ...
