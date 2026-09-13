from typing import Protocol
from neftecode.domain.production.scenario import Scenario


class ScenarioRepository(Protocol):
    def get(self, scenario_id: str) -> Scenario: ...
