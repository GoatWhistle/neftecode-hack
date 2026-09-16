import json
import threading
from http.client import HTTPConnection
from pathlib import Path

from neftecode.bootstrap import run_demo_decision
from neftecode.presentation.demo import Demo
from neftecode.services.common import ServiceHTTPServer, make_handler
from neftecode.services.data_service import DataService
from neftecode.services.decision_service import DecisionService
from neftecode.services.gateway_service import GatewayService, make_gateway_handler

ROOT = Path(__file__).parents[2]


def start(service, name, handler_factory=make_handler):
    server = ServiceHTTPServer(("127.0.0.1", 0), handler_factory(service) if handler_factory is make_gateway_handler
                               else handler_factory(service.routes(), service.ready, name))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def get(server, path, request_id="gateway-integration"):
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=20)
    connection.request("GET", path, headers={"X-Request-ID": request_id})
    response = connection.getresponse()
    payload = json.loads(response.read())
    connection.close()
    return response.status, payload


def test_gateway_legacy_decide_matches_local_decision():
    data, data_thread = start(DataService(ROOT), "data-service")
    decision_service = DecisionService(
        f"http://127.0.0.1:{data.server_port}", "http://127.0.0.1:1", timeout_s=1,
    )
    decision, decision_thread = start(decision_service, "decision-service")
    gateway_service = GatewayService(
        f"http://127.0.0.1:{data.server_port}", f"http://127.0.0.1:{decision.server_port}", timeout_s=20,
    )
    gateway, gateway_thread = start(gateway_service, "gateway-service", make_gateway_handler)
    try:
        status, payload = get(gateway, "/api/decide?scenario=baseline")
        assert status == 200
        local = run_demo_decision(json.loads((ROOT / "config/scenarios/baseline.json").read_text()),
                                  {"decision_time": "2026-01-05T08:00:00", "lab_value": 8.0,
                                   "lab_age_hours": 5.0, "lab_usable": True, "pak_value": 8.4,
                                   "pak_age_minutes": 10.0, "pak_usable": True, "pak_frozen": False,
                                   "pak_conflict": False, "telemetry_missing_fraction": 0.0,
                                   "origin": "synthetic_scenario_state"}, 400)
        assert payload["decision"]["decision_id"] == local["decision"]["decision_id"]
        assert get(gateway, "/v1/capabilities")[0] == 200
    finally:
        for server, thread in ((gateway, gateway_thread), (decision, decision_thread), (data, data_thread)):
            server.shutdown(); server.server_close(); thread.join(timeout=3)


def test_gateway_unavailable_upstream_keeps_legacy_screen_status():
    service = GatewayService("http://127.0.0.1:1", "http://127.0.0.1:2", timeout_s=0.2)
    gateway, thread = start(service, "gateway-service", make_gateway_handler)
    try:
        status, payload = get(gateway, "/api/decide?scenario=baseline")
        assert status == 200
        assert payload["state"] == "error"
        assert "decision" not in payload
    finally:
        gateway.shutdown(); gateway.server_close(); thread.join(timeout=3)


def test_gateway_readiness_exception_is_standard_503():
    class BrokenReady(GatewayService):
        def ready(self):
            raise RuntimeError("dependency probe failed")
    gateway, thread = start(BrokenReady("http://127.0.0.1:1", "http://127.0.0.1:2"), "gateway-service", make_gateway_handler)
    try:
        status, payload = get(gateway, "/readyz")
        assert status == 503 and payload["error"]["code"] == "readiness_unavailable"
    finally:
        gateway.shutdown(); gateway.server_close(); thread.join(timeout=3)


def test_gateway_generates_unique_request_id_and_propagates_header():
    seen = []
    data = ServiceHTTPServer(("127.0.0.1", 0), make_handler({
        "/v1/scenarios": lambda request: (seen.append(request.request_id) or {"scenarios": ["baseline"]}),
    }, service_name="data-service"))
    data_thread = threading.Thread(target=data.serve_forever, daemon=True); data_thread.start()
    gateway, gateway_thread = start(GatewayService(f"http://127.0.0.1:{data.server_port}", "http://127.0.0.1:2"), "gateway-service", make_gateway_handler)
    try:
        connection = HTTPConnection("127.0.0.1", gateway.server_port, timeout=2)
        connection.request("GET", "/api/scenarios")
        response = connection.getresponse(); response.read(); first = response.getheader("X-Request-ID"); connection.close()
        connection = HTTPConnection("127.0.0.1", gateway.server_port, timeout=2)
        connection.request("GET", "/api/scenarios")
        response = connection.getresponse(); response.read(); second = response.getheader("X-Request-ID"); connection.close()
        assert first and second and first != second and seen == [first, second]
    finally:
        gateway.shutdown(); gateway.server_close(); gateway_thread.join(timeout=3)
        data.shutdown(); data.server_close(); data_thread.join(timeout=3)


def test_gateway_upstream_down_still_serves_html_error_page():
    gateway, thread = start(GatewayService("http://127.0.0.1:1", "http://127.0.0.1:2"), "gateway-service", make_gateway_handler)
    try:
        connection = HTTPConnection("127.0.0.1", gateway.server_port, timeout=2)
        connection.request("GET", "/")
        response = connection.getresponse(); body = response.read().decode(); content_type = response.getheader("Content-Type"); connection.close()
        assert response.status == 200 and content_type.startswith("text/html") and "Ошибка" in body
    finally:
        gateway.shutdown(); gateway.server_close(); thread.join(timeout=3)


def test_gateway_waits_long_enough_for_an_agentic_decision():
    from neftecode.services.gateway_service import GatewayService

    service = GatewayService()
    assert service.decision_timeout_s >= 600
    assert service.client.timeout_s == 10.0
