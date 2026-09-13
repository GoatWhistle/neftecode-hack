import json
import threading
from datetime import datetime
from http.client import HTTPConnection

import pytest

from neftecode.services import (ServiceEnvelope, ServiceError, ServiceHTTPClient,
                                ServiceHTTPServer, ServiceSettings, clean, decode_json,
                                encode_json, make_handler)


def test_json_clean_and_envelope_are_transport_neutral():
    envelope = ServiceEnvelope.success({"when": datetime(2026, 1, 1), "bad": float("nan")}, "r-1")
    assert decode_json(encode_json(envelope.to_dict())) == {
        "contract_version": "v1", "service": "unknown", "ok": True,
        "data": {"when": "2026-01-01T00:00:00", "bad": None}, "request_id": "r-1"
    }
    assert clean((1, {"x": True})) == [1, {"x": True}]


def test_service_error_serializes_status_and_details():
    error = ServiceError("нет сценария", status=422, code="scenario_rejected", details={"field": "x"})
    assert error.to_dict() == {"code": "scenario_rejected", "message": "нет сценария",
                               "retryable": False, "details": {"field": "x"}}
    assert ServiceEnvelope.failure(error).to_dict()["ok"] is False


def test_settings_read_env_and_reject_bad_values(monkeypatch):
    monkeypatch.setenv("TEST_PORT", "9012")
    monkeypatch.setenv("TEST_REQUEST_TIMEOUT_S", "1.5")
    settings = ServiceSettings.from_env("TEST_")
    assert settings.port == 9012 and settings.request_timeout_s == 1.5
    monkeypatch.setenv("TEST_PORT", "oops")
    with pytest.raises(ValueError, match="TEST_PORT"):
        ServiceSettings.from_env("TEST_")


def test_settings_service_default_allows_explicit_env_8765(monkeypatch):
    monkeypatch.setenv("DATA_PORT", "8765")
    settings = ServiceSettings.from_env("DATA_", ServiceSettings(port=8766))
    assert settings.port == 8765


def running_server(routes, readiness=None):
    server = ServiceHTTPServer(("127.0.0.1", 0), make_handler(routes, readiness))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def get(server, path):
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=2)
    connection.request("GET", path, headers={"X-Request-ID": "test-id"})
    response = connection.getresponse()
    payload = json.loads(response.read())
    connection.close()
    return response.status, payload


def test_handler_health_readiness_routes_and_errors():
    server, thread = running_server({"/echo": lambda request: {"query": request.query}}, lambda: False)
    try:
        assert get(server, "/healthz") == (200, {"contract_version": "v1", "service": "service",
                                                   "ok": True, "data": {"status": "ok"}, "request_id": "test-id"})
        status, payload = get(server, "/readyz")
        assert status == 503 and payload["error"]["code"] == "not_ready"
        assert get(server, "/echo?a=1")[1]["data"]["query"] == {"a": ["1"]}
        assert get(server, "/missing")[0] == 404
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_handler_generates_request_id_and_rejects_post_headers_and_size():
    settings = ServiceSettings(max_body_bytes=3, max_response_bytes=1000)
    server, thread = running_server({"/echo": lambda request: request.body})
    # The helper defaults are intentionally independent; use a handler with strict settings.
    server.shutdown(); server.server_close(); thread.join(timeout=2)
    server, thread = running_server({"/echo": lambda request: request.body})
    server.RequestHandlerClass = make_handler({"/echo": lambda request: request.body}, service_name="echo", settings=settings)
    # A fresh server is needed for the handler class to be selected at construction time.
    server.shutdown(); server.server_close(); thread.join(timeout=2)
    server = ServiceHTTPServer(("127.0.0.1", 0), make_handler({"/echo": lambda request: request.body}, service_name="echo", settings=settings))
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=2)
        connection.request("POST", "/echo", body="{}", headers={"Content-Length": "2"})
        response = connection.getresponse(); assert response.status == 415; response.read(); connection.close()
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=2)
        connection.request("POST", "/echo", body="{}", headers={"Content-Length": "4", "Content-Type": "application/json"})
        response = connection.getresponse(); assert response.status == 413; response.read(); connection.close()
        status, payload = get(server, "/healthz")
        assert status == 200 and payload["request_id"] == "test-id" and payload["service"] == "echo"
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_client_rejects_invalid_contract_and_readiness_exception_is_503():
    server, thread = running_server({}, lambda: (_ for _ in ()).throw(RuntimeError("boot")))
    try:
        status, payload = get(server, "/readyz")
        assert status == 503
        assert payload["error"] == {"code": "readiness_unavailable",
                                    "message": "Сервис не готов", "retryable": True}
        with pytest.raises(ServiceError, match="Некорректный ответ"):
            ServiceHTTPClient()._decode(encode_json({"ok": 1}), 200)
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_post_requires_length_and_rejects_chunked_transfer():
    server, thread = running_server({"/echo": lambda request: request.body})
    try:
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=2)
        connection.putrequest("POST", "/echo")
        connection.endheaders()
        response = connection.getresponse()
        assert response.status == 411
        assert json.loads(response.read())["error"]["code"] == "length_required"
        connection.close()

        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=2)
        connection.putrequest("POST", "/echo")
        connection.putheader("Transfer-Encoding", "chunked")
        connection.endheaders()
        response = connection.getresponse()
        assert response.status == 400
        assert json.loads(response.read())["error"]["code"] == "unsupported_transfer_encoding"
        connection.close()
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_http_client_maps_upstream_error():
    server, thread = running_server({"/fail": lambda request: (_ for _ in ()).throw(ServiceError("нет", 422, "rejected"))})
    try:
        with pytest.raises(ServiceError) as caught:
            ServiceHTTPClient(1).request("GET", f"http://127.0.0.1:{server.server_port}/fail")
        assert caught.value.status == 422 and caught.value.code == "rejected"
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)
