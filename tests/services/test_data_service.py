import json
import threading
from http.client import HTTPConnection
from pathlib import Path

from neftecode.services.common import ServiceHTTPServer, make_handler
from neftecode.services.data_service import DataService

ROOT = Path(__file__).parents[2]


def running(service):
    server = ServiceHTTPServer(("127.0.0.1", 0), make_handler(service.routes(), service.ready, "data-service"))
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    return server, thread


def request(server, method, path, body=None):
    conn = HTTPConnection("127.0.0.1", server.server_port, timeout=2)
    raw = None if body is None else json.dumps(body).encode()
    headers = {} if raw is None else {"Content-Type": "application/json"}
    conn.request(method, path, raw, headers); response = conn.getresponse()
    payload = json.loads(response.read()); conn.close(); return response.status, payload


def test_data_routes_readiness_and_capabilities():
    server, thread = running(DataService(ROOT))
    try:
        assert request(server, "GET", "/healthz")[0] == 200
        assert request(server, "GET", "/readyz")[0] == 200
        status, payload = request(server, "GET", "/v1/scenarios")
        assert status == 200 and "baseline" in payload["data"]["scenarios"]
        status, payload = request(server, "GET", "/v1/capabilities")
        assert status == 200 and payload["data"]["scenarios"] is True
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_scenario_get_and_malformed_input():
    service = DataService(ROOT); server, thread = running(service)
    try:
        status, payload = request(server, "POST", "/v1/scenarios/get", {"scenario_id": "baseline"})
        assert status == 200 and payload["data"]["id"] == "baseline"
        status, payload = request(server, "POST", "/v1/scenarios/get", {"scenario_id": "../secret"})
        assert status == 400 and payload["error"]["code"] == "invalid_scenario_id"
        status, payload = request(server, "POST", "/v1/scenarios/get", {})
        assert status == 400
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_missing_task_is_graceful_and_snapshot_has_no_dataframe(tmp_path):
    root = tmp_path; (root / "config/scenarios").mkdir(parents=True)
    (root / "config/scenarios/x.json").write_text(json.dumps({"id": "x"}), encoding="utf-8")
    service = DataService(root); server, thread = running(service)
    try:
        assert request(server, "GET", "/readyz")[0] == 200
        status, payload = request(server, "GET", "/v1/capabilities")
        assert status == 200 and payload["data"]["measurements"] is False
        status, payload = request(server, "POST", "/v1/snapshots", {"at": "2026-01-01T00:00:00"})
        assert status == 503 and payload["error"]["code"] == "measurements_unavailable"
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)
