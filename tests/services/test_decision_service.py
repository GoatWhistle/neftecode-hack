import json
import threading
from http.client import HTTPConnection
from pathlib import Path

import pytest

from neftecode.bootstrap import run_demo_decision
from neftecode.services.common import ServiceHTTPServer, make_handler
from neftecode.services.data_service import DataService
from neftecode.services.model_service import ModelService
from neftecode.services.decision_service import DecisionService
from neftecode.infrastructure.live.advisor import load_response_model
from neftecode.domain.advisory.optimizer import DEFAULT_BUDGET

ROOT = Path(__file__).parents[2]


def test_http_decision_without_budget_uses_the_product_default():
    from neftecode.services.common import Request

    class CapturingDecisionService(DecisionService):
        def _decision(self, raw, state, budget, trust_cfg=None, trust_origin=None, snapshot=None):
            return {"budget": budget}

    result = CapturingDecisionService().decide(Request("POST", "/v1/decisions", {}, {
        "scenario": {}, "state": {},
    }))
    assert result == {"budget": DEFAULT_BUDGET}


def test_decision_service_main_uses_the_normalized_default_root(monkeypatch):
    from neftecode.services import decision_service as module

    seen = {}
    monkeypatch.delenv("NEFTECODE_ROOT", raising=False)
    monkeypatch.setattr(module, "build_decision_factory",
                        lambda dotenv_path: seen.setdefault("dotenv_path", dotenv_path))
    monkeypatch.setattr(module, "load_response_model_with_digest",
                        lambda root, out: seen.update(model_root=root, model_artifacts=out) or (None, None))
    monkeypatch.setattr(module, "serve", lambda *args: 0)

    assert module.main([]) == 0
    assert seen == {"dotenv_path": Path(".env"), "model_root": Path("."),
                    "model_artifacts": Path("artifacts")}


def test_decision_service_main_honours_a_separate_artifacts_directory(monkeypatch, tmp_path):
    from neftecode.services import decision_service as module

    root, artifacts = tmp_path / "project", tmp_path / "models"
    seen = {}
    monkeypatch.setattr(module, "build_decision_factory", lambda **kwargs: None)
    monkeypatch.setattr(module, "load_response_model_with_digest",
                        lambda model_root, out: seen.update(root=model_root, artifacts=out) or (None, None))
    monkeypatch.setattr(module, "serve", lambda *args: 0)

    assert module.main(["--root", str(root), "--artifacts", str(artifacts)]) == 0
    assert seen == {"root": root, "artifacts": artifacts}


def start(service, name):
    server = ServiceHTTPServer(("127.0.0.1", 0), make_handler(service.routes(), service.ready, name))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def call(server, method, path, body=None, request_id="integration-1"):
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=20)
    raw = None if body is None else json.dumps(body).encode()
    headers = {"X-Request-ID": request_id}
    if raw is not None:
        headers["Content-Type"] = "application/json"
    connection.request(method, path, raw, headers)
    response = connection.getresponse()
    payload = json.loads(response.read())
    connection.close()
    return response.status, payload


@pytest.mark.skipif(
    not (ROOT / "task" / "data" / "avt_tags.csv").is_file()
    or not (ROOT / "artifacts" / "model.pkl").is_file(),
    reason="для проверки реального live-контракта нужны локальные task/ и model.pkl",
)
def test_real_data_model_decision_live_contract():
    data, data_thread = start(DataService(ROOT), "data-service")
    model, model_thread = start(ModelService(ROOT), "model-service")
    decision_service = DecisionService(
        f"http://127.0.0.1:{data.server_port}",
        f"http://127.0.0.1:{model.server_port}",
        timeout_s=20, response_model=load_response_model(ROOT),
    )
    decision, decision_thread = start(decision_service, "decision-service")
    try:
        status, payload = call(decision, "POST", "/v1/live/advice", {
            "at": "2026-01-05T08:00:00", "scenario_id": "baseline", "budget": 250,
        })
        assert status == 200
        result = payload["data"]
        assert result["scenario_id"] == "baseline"
        assert result["forecast"]["model"] == "last_pak_bc"
        assert result["forecast"]["value"] == 7.582309246063232
        assert result["forecast"]["upper"] == 10.819024410387263
        assert result["bound_inflow_sulfur_mgkg"] == 10.819
        assert result["bound_sulfur_mgkg"] == 4.5624
        assert result["binding"]["controls"]["ht_reactor_inlet_temp_c"]["current"]["source"] == "measured"
        assert result["binding"]["response_model"]["provenance"] == "derived"
        assert result["decision"]["status"] == "hold"
        assert result["decision"]["refusal"] is None
        assert result["decision"]["tank_estimate"]["same"] == 3
        assert result["decision"]["tank_estimate"]["baseline_status"] == "hold"
        assert result["decision"]["tank_park"]["model_version"] == "tank-park/1"
        assert set(result["inventories"]) == {"main", "reserve", "light"}
        assert {source["name"] for source in result["sources"]} == {"ЛИМС", "ПАК"}
        assert payload["request_id"] == "integration-1"
    finally:
        for server, thread in ((decision, decision_thread), (model, model_thread), (data, data_thread)):
            server.shutdown(); server.server_close(); thread.join(timeout=3)


def test_live_upstream_failure_is_explicit():
    service = DecisionService("http://127.0.0.1:1", "http://127.0.0.1:2", timeout_s=0.2)
    server, thread = start(service, "decision-service")
    try:
        status, payload = call(server, "POST", "/v1/live/advice", {
            "at": "2026-01-05T08:00:00", "scenario_id": "baseline",
        })
        assert status in (503, 504)
        assert payload["ok"] is False
        assert payload["error"]["code"] in ("upstream_unavailable", "upstream_timeout")
        assert "decision" not in payload.get("data", {})
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=3)


def test_live_rejected_snapshot_cannot_be_overridden_by_healthy_state():
    from types import SimpleNamespace
    from neftecode.services.common import Request

    raw = json.loads((ROOT / 'config/scenarios/baseline.json').read_text(encoding="utf-8"))
    state = {'decision_time': '2026-01-05T08:00:00', 'lab_value': 8.0,
             'lab_age_hours': 5.0, 'lab_usable': True, 'pak_value': 8.4,
             'pak_age_minutes': 10.0, 'pak_usable': True, 'pak_frozen': False,
             'pak_conflict': False, 'telemetry_missing_fraction': 0.0}
    sources = {'ЛИМС': {'name': 'ЛИМС', 'usable': False, 'status': 'unusable'}}

    class Client:
        def request(self, method, url, body=None, headers=None):
            if url.endswith('/v1/scenarios/get'):
                return SimpleNamespace(data=raw)
            if url.endswith('/v1/snapshots'):
                return SimpleNamespace(data={'at': state['decision_time'], 'state': state,
                    'trust': {'usable': False, 'sources': sources,
                              'refusal_reason': 'Отклонено внешней проверкой'}})
            raise AssertionError('Rejected snapshot must not reach forecast')

    service = DecisionService()
    service.client = Client()
    result = service.live(Request('POST', '/v1/live/advice', {},
        {'at': state['decision_time'], 'scenario_id': 'baseline', 'budget': 30}))
    assert result['decision']['status'] == 'refuse'
    assert result['decision']['immediate_action'] is None
    assert result['decision']['reason'] == 'Отклонено внешней проверкой'
    assert result['sources'] == list(sources.values())
    assert result['inventories'] == {tank['tank_id']: tank.get('inventory', {}).get('value', 0.0)
                                     for tank in raw['tanks']}
    reserve = next(t for t in raw['tanks'] if t['tank_id'] == 'reserve')
    assert reserve.get('on_demand') is True and result['inventories']['reserve'] == 0.0


def test_live_binding_failure_keeps_http_error_contract():
    from types import SimpleNamespace
    from neftecode.services.common import Request, ServiceError

    raw = json.loads((ROOT / 'config/scenarios/baseline.json').read_text(encoding="utf-8"))

    class Client:
        def request(self, method, url, body=None, headers=None):
            if url.endswith('/v1/scenarios/get'):
                return SimpleNamespace(data=raw)
            if url.endswith('/v1/snapshots'):
                return SimpleNamespace(data={'at': '2026-01-05T08:00:00', 'state': {},
                                             'trust': {'usable': True}})
            return SimpleNamespace(data={'available': True, 'model': 'test',
                'value': 8.0, 'lower': 7.0, 'upper': 6.0})

    service = DecisionService()
    service.client = Client()
    with pytest.raises(ServiceError) as error:
        service.live(Request('POST', '/v1/live/advice', {},
            {'at': '2026-01-05T08:00:00', 'scenario_id': 'baseline'}))
    assert error.value.status == 422
    assert error.value.code == 'forecast_binding_failed'
