import json

from neftecode.infrastructure.artifacts import JsonArtifactSink
from neftecode.infrastructure.scenarios import FileScenarioRepository, HttpScenarioRepository


def test_file_scenario_repository_loads_by_id_and_rejects_mismatch(tmp_path):
    source = "config/scenarios/baseline.json"
    payload = json.loads(open(source, encoding="utf-8").read())
    (tmp_path / "baseline.json").write_text(json.dumps(payload), encoding="utf-8")
    scenario = FileScenarioRepository(tmp_path).get("baseline")
    assert scenario.scenario_id == "baseline"


def test_file_scenario_repository_lists_names_and_returns_raw_json():
    repository = FileScenarioRepository("config/scenarios")
    assert {"baseline", "sour_crude", "no_feasible", "ample_reserve"} <= set(repository.names())
    assert repository.names() == sorted(repository.names())
    assert repository.raw("baseline") == json.loads(open("config/scenarios/baseline.json", encoding="utf-8").read())


class RecordingClient:
    def __init__(self, raw):
        self.raw, self.calls = raw, []

    def request(self, method, url, payload=None, timeout_s=None, headers=None):
        self.calls.append((method, url, payload, dict(headers or {})))
        data = {"scenarios": ["baseline"]} if url.endswith("/v1/scenarios") else self.raw
        return type("Envelope", (), {"data": data})()


def test_http_scenario_repository_asks_the_data_service_with_the_request_id():
    raw = json.loads(open("config/scenarios/baseline.json", encoding="utf-8").read())
    client = RecordingClient(raw)
    repository = HttpScenarioRepository(client, "http://data:8766/").for_request("r-1")
    assert repository.names() == ["baseline"]
    assert repository.raw("baseline") == raw
    assert repository.get("baseline").scenario_id == "baseline"
    assert client.calls[:2] == [
        ("GET", "http://data:8766/v1/scenarios", None, {"X-Request-ID": "r-1"}),
        ("POST", "http://data:8766/v1/scenarios/get", {"scenario_id": "baseline"}, {"X-Request-ID": "r-1"}),
    ]


def test_json_artifact_sink_writes_serializable_report(tmp_path):
    path = JsonArtifactSink(tmp_path).save("report", {"status": "ok", "values": [1, 2]})
    assert path.endswith("report.json")
    assert json.loads(open(path, encoding="utf-8").read()) == {"status": "ok", "values": [1, 2]}
