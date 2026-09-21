from typing import Protocol
from neftecode.domain.production.scenario import Scenario


class ScenarioRepository(Protocol):
    """Источник сценариев: файлы `config/scenarios` или data-service по HTTP."""

    def names(self) -> list[str]: ...

    def raw(self, scenario_id: str) -> dict: ...

    def get(self, scenario_id: str) -> Scenario: ...


class SnapshotRepository(Protocol):
    """Сохранённые реальные срезы. `all()` — по возрастанию времени; подпись среза — поле `label`."""

    def all(self) -> list[dict]: ...

    def get(self, key: str) -> dict: ...
