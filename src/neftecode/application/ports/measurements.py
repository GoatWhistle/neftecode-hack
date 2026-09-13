from typing import Protocol, Sequence
from neftecode.domain.monitoring.entities import Observation


class MeasurementSource(Protocol):
    def measurements(self, at: str | None = None) -> Sequence[Observation]: ...
