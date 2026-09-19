import json
import pickle
import threading
from http.client import HTTPConnection

import pytest

from neftecode.services.common import ServiceError, ServiceHTTPServer, make_handler, content_hash
from neftecode.services.model_service import ModelService


def running(service):
    server = ServiceHTTPServer(("127.0.0.1", 0), make_handler(service.routes(), service.ready, "model-service"))
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    return server, thread


def request(server, method, path, body=None):
    conn = HTTPConnection("127.0.0.1", server.server_port, timeout=2)
    raw = None if body is None else json.dumps(body).encode()
    headers = {} if raw is None else {"Content-Type": "application/json"}
    conn.request(method, path, raw, headers); response = conn.getresponse()
    payload = json.loads(response.read()); conn.close(); return response.status, payload


def test_missing_model_is_unavailable_without_traceback(tmp_path):
    service = ModelService(tmp_path, tmp_path / "artifacts"); server, thread = running(service)
    try:
        assert request(server, "GET", "/readyz")[0] == 503
        status, payload = request(server, "GET", "/v1/models")
        assert status == 503 and payload["error"]["code"] == "model_unavailable"
        status, payload = request(server, "POST", "/v1/forecast", {})
        assert status == 400 and payload["error"]["code"] == "invalid_snapshot"
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_malformed_forecast_input_is_4xx(tmp_path):
    service = ModelService(tmp_path, tmp_path / "artifacts"); server, thread = running(service)
    try:
        status, payload = request(server, "POST", "/v1/forecast", {"snapshot": []})
        assert status == 400 and payload["error"]["code"] == "invalid_snapshot"
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_selected_simple_baseline_is_a_real_available_model(tmp_path):
    artifacts = tmp_path / "artifacts"; artifacts.mkdir()
    bundle = {
        "models": {}, "columns": {}, "candidates": ["last_lab", "last_pak"],
        "selected": "last_pak", "fallback": "last_lab",
        "radii": {"last_pak": 0.1, "last_lab": 0.2},
        "config": {"calibration_end": "2025-07-01"},
        "manifest": {"fingerprint": "test"},
    }
    with (artifacts / "model.pkl").open("wb") as stream:
        pickle.dump(bundle, stream)
    (artifacts / "manifest.json").write_text(json.dumps({"fingerprint": "test"}), encoding="utf-8")
    service = ModelService(tmp_path, artifacts); server, thread = running(service)
    try:
        assert request(server, "GET", "/readyz")[0] == 200
        status, payload = request(server, "GET", "/v1/models")
        assert status == 200 and payload["data"]["selected"] == "last_pak"
        snapshot = {"schema_version": "v1", "at": "2026-01-05T08:00:00",
                    "state": {"decision_time": "2026-01-05T08:00:00"},
                    "trust": {"usable": True}, "features": {"pak.sulfur": 7.5, "lab.sulfur": 7.0},
                    "source_period": {"min": "2026-01-01T00:00:00", "max": "2026-01-10T00:00:00"},
                    "feature_schema": [], "feature_schema_hash": content_hash([])}
        snapshot["snapshot_id"] = content_hash(snapshot)
        status, payload = request(server, "POST", "/v1/forecast", {"snapshot": snapshot})
        forecast = payload["data"]
        assert status == 200 and forecast["available"] is True
        assert forecast["model"] == "last_pak" and forecast["value"] == 7.5
        assert forecast["lower"] < 7.5 < forecast["upper"]
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_bias_corrected_candidate_requires_both_snapshot_features():
    snapshot = {
        "schema_version": "v1", "at": "2026-01-05T08:00:00",
        "state": {"decision_time": "2026-01-05T08:00:00"},
        "trust": {"usable": True}, "features": {"pak.sulfur": 7.5},
        "source_period": {"min": "2026-01-01T00:00:00", "max": "2026-01-10T00:00:00"},
        "feature_schema": [], "feature_schema_hash": content_hash([]),
    }
    snapshot["snapshot_id"] = content_hash(snapshot)
    bundle = {"selected": "last_pak_bc", "fallback": "last_pak", "columns": {}}
    with pytest.raises(ServiceError, match="отсутствуют признаки модели") as caught:
        ModelService._validate_snapshot(snapshot, bundle)
    assert caught.value.code == "invalid_features"
