from typing import Mapping, Protocol
from neftecode.domain.monitoring.entities import ForecastValue


class ForecastModel(Protocol):
    def predict(self, features: Mapping[str, float | None]) -> ForecastValue: ...


class ModelRepository(Protocol):
    def get_model(self, name: str) -> ForecastModel: ...
