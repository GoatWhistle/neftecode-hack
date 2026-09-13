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

ROOT = Path(__file__).parents[2]


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
        timeout_s=20,
    )
    decision, decision_thread = start(decision_service, "decision-service")
    try:
        status, payload = call(decision, "POST", "/v1/live/advice", {
            "at": "2026-01-05T08:00:00", "scenario_id": "baseline", "budget": 250,
        })
        assert status == 200
        result = payload["data"]
        assert result["scenario_id"] == "baseline"
        assert result["forecast"]["value"] == 5.883740425109863
        assert result["forecast"]["upper"] == 9.167584757282347
        assert result["bound_sulfur_mgkg"] == 9.1676
        assert result["decision"]["status"] == "hold"
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
