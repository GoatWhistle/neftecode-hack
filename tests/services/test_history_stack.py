"""P4 через настоящий HTTP-стек: произвольный момент истории даёт то же решение, что serve.

gateway не читает task/ и модель: срез момента готовит decision-service из data-service
(причинное состояние) и model-service (две ветви прогноза на одном snapshot_id).
"""
from pathlib import Path

import pytest

from neftecode.application.history.time import HistoryError
from neftecode.bootstrap import make_demo_service
from neftecode.infrastructure.agentic.factory import build_decision_factory
from neftecode.infrastructure.artifacts.provenance import loaded_provenance
from neftecode.infrastructure.history.source import LocalHistorySource
from neftecode.infrastructure.live.response_model import load_response_model_with_digest
from neftecode.services.common import ServiceHTTPServer, make_handler
from neftecode.services.data_service import DataService
from neftecode.services.decision_service import DecisionService
from neftecode.services.gateway_service import GatewayService, make_gateway_handler
from neftecode.services.model_service import ModelService

from test_http_contract import _serve, _stop, get_json

ROOT = Path(__file__).parents[2]
AT = "2026-01-05T08:07:13"

pytestmark = pytest.mark.skipif(not LocalHistorySource(ROOT, ROOT / "artifacts").capability()["available"],
                                reason="в поставке нет полного task/ и модели")


@pytest.fixture(scope="module")
def pair():
    data = _serve(ServiceHTTPServer(("127.0.0.1", 0), make_handler(DataService(ROOT).routes(), None, "data-service")))
    model = _serve(ServiceHTTPServer(("127.0.0.1", 0), make_handler(ModelService(ROOT, ROOT / "artifacts").routes(),
                                                                   None, "model-service")))
    response_model, sha = load_response_model_with_digest(ROOT, ROOT / "artifacts")
    decision_service = DecisionService(
        f"http://127.0.0.1:{data[0].server_port}", f"http://127.0.0.1:{model[0].server_port}", timeout_s=120,
        decision_factory=build_decision_factory(
            {"AGENTIC_DECISION_ENABLED": "1", "LLM_PROVIDER": "scripted"},
            dotenv_path=ROOT / ".env",
        ),
        response_model=response_model, provenance=loaded_provenance(ROOT, ROOT / "artifacts", sha))
    decision = _serve(ServiceHTTPServer(("127.0.0.1", 0), make_handler(decision_service.routes(), None,
                                                                        "decision-service")))
    gateway_service = GatewayService(f"http://127.0.0.1:{data[0].server_port}",
                                     f"http://127.0.0.1:{decision[0].server_port}", timeout_s=120, root=ROOT)
    gateway = _serve(ServiceHTTPServer(("127.0.0.1", 0), make_gateway_handler(gateway_service)))
    serve = make_demo_service(ROOT)
    # Холодная загрузка источников (секунды) — не предмет проверки: прогреваем оба пути заранее.
    get_json(gateway[0], "/api/history")
    serve.history_catalog({})
    try:
        yield serve, gateway[0]
    finally:
        _stop(gateway, decision, model, data)


@pytest.mark.parametrize("fault", ["healthy", "frozen_pak", "both_broken"])
def test_arbitrary_moment_gives_the_same_decision_in_serve_and_stack(pair, fault):
    serve, gateway = pair
    query = {"scenario": ["baseline"], "at": [AT], "fault": [fault]}
    local = serve.recompute(query)
    status, remote = get_json(gateway, f"/api/decide?scenario=baseline&at={AT}&fault={fault}")
    assert status == 200
    assert remote["state"] == local["state"]
    assert remote["state"] in {"decision", "refusal"}
    assert remote["decision"]["status"] == local["decision"]["status"]
    assert remote["decision"]["decision_id"] == local["decision"]["decision_id"]
    assert remote["decision_time"] == local["decision_time"] == AT
    for payload in (local, remote):
        assert payload["history"]["requested_at"] == payload["history"]["effective_at"] == AT
        assert payload["run_meta"]["conditions_requested"]["at"] == AT
        assert payload["run_meta"]["input_parts"]["snapshot_sha256"] is not None
    if fault == "both_broken":
        assert local["decision"]["status"] == "refuse"


def test_catalog_and_coverage_agree(pair):
    serve, gateway = pair
    local = serve.history_catalog({})
    status, remote = get_json(gateway, "/api/history")
    assert status == 200
    assert remote["arbitrary"]["available"] is local["arbitrary"]["available"] is True
    assert remote["coverage"] == local["coverage"]
    assert [item["snapshot"] for item in remote["items"]] == [item["snapshot"] for item in local["items"]]


@pytest.mark.parametrize("at, code", [("2026-01-05T08:07:13Z", "unknown_timezone"),
                                       ("2025-06-01T00:00:00", "model_not_available")])
def test_invalid_moment_is_explained_and_not_replaced(pair, at, code):
    serve, gateway = pair
    with pytest.raises(HistoryError) as local:
        serve.decide({"scenario": ["baseline"], "at": [at]})
    assert local.value.code == code
    status, remote = get_json(gateway, f"/api/decide?scenario=baseline&at={at}")
    assert remote["state"] == "error"
    assert "decision" not in remote or remote.get("decision") is None
    status, overview = get_json(gateway, f"/api/history/overview?start={at}&end={at}&points=2")
    assert status == 422 and overview["code"] == code
