import json
from pathlib import Path

from neftecode.domain.production.scenario import Scenario, ScenarioError
from neftecode.infrastructure.config.scenario import load_scenario
from neftecode.infrastructure.live.snapshots import load_snapshots, snapshot_name


def read_raw_scenario(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


class FileScenarioRepository:
    """Сценарии из каталога JSON-файлов (`config/scenarios`); имя сценария — имя файла без `.json`."""

    def __init__(self, directory: str | Path):
        self.directory = Path(directory)

    def names(self) -> list[str]:
        return sorted(path.stem for path in self.directory.glob("*.json"))

    def raw(self, scenario_id: str) -> dict:
        return read_raw_scenario(self.directory / f"{scenario_id}.json")

    def get(self, scenario_id: str) -> Scenario:
        path = self.directory / f"{scenario_id}.json"
        if not path.is_file():
            raise ScenarioError(f"Сценарий «{scenario_id}» не найден в {self.directory}")
        scenario = load_scenario(path)
        if scenario.scenario_id != scenario_id:
            raise ScenarioError(f"{path}: id сценария не совпадает с запрошенным «{scenario_id}»")
        return scenario


class FileSnapshotRepository:
    """Реальные срезы из `artifacts/snapshots/*.json`, проверенные на отпечаток модели в `manifest.json`."""

    def __init__(self, out: str | Path):
        self.out = Path(out)

    def all(self) -> list[dict]:
        return load_snapshots(self.out)

    def get(self, key: str) -> dict:
        for item in self.all():
            if snapshot_name(item) == key:
                return item
        raise KeyError(f"Срез «{key}» не найден в {self.out / 'snapshots'}")

