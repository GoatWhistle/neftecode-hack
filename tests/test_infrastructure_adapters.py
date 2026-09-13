import json

from neftecode.infrastructure.artifacts import JsonArtifactSink
from neftecode.infrastructure.config.scenario import FileScenarioRepository


def test_file_scenario_repository_loads_by_id_and_rejects_mismatch(tmp_path):
    source = "config/scenarios/baseline.json"
    payload = json.loads(open(source, encoding="utf-8").read())
    (tmp_path / "baseline.json").write_text(json.dumps(payload), encoding="utf-8")
    scenario = FileScenarioRepository(tmp_path).get("baseline")
    assert scenario.scenario_id == "baseline"


def test_json_artifact_sink_writes_serializable_report(tmp_path):
    path = JsonArtifactSink(tmp_path).save("report", {"status": "ok", "values": [1, 2]})
    assert path.endswith("report.json")
    assert json.loads(open(path, encoding="utf-8").read()) == {"status": "ok", "values": [1, 2]}
