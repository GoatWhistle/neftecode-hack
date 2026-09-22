"""Контракт интерфейса через настоящий HTTP-стек: gateway → decision → data на свободных портах.

Проверяет то, что UI читает из /api/decide и /api/stream: run_meta с условиями, отпечатком и
версиями из считающего процесса; живые этапы и события агентов до итогового screen; одинаковый
смысл результата у serve и у стека; отсутствие агентных вызовов при отказе по данным.
"""
import json
import threading
from http.client import HTTPConnection
from pathlib import Path

import pytest

from neftecode.application.progress import emit
from neftecode.bootstrap import make_demo_service
from neftecode.infrastructure.agentic import factory as agentic_factory
from neftecode.infrastructure.agentic.factory import build_decision_factory
from neftecode.infrastructure.artifacts.provenance import loaded_provenance
from neftecode.infrastructure.live.response_model import load_response_model_with_digest
from neftecode.infrastructure.llm.demo_policy import demo_llm
from neftecode.services.common import ServiceHTTPServer, make_handler
from neftecode.services.data_service import DataService
from neftecode.services.decision_service import DecisionService
from neftecode.services.gateway_service import GatewayService, make_gateway_handler

ROOT = Path(__file__).parents[2]
RISK = "scenario=sour_crude&snapshot=20260724-030000&fault=healthy"
REFUSE = "scenario=baseline&snapshot=20260416-101000&fault=both_broken"
SCRIPTED = {"AGENTIC_DECISION_ENABLED": "1", "LLM_PROVIDER": "scripted"}


class CountingLLM:
    """Scripted-политика с подсчётом обращений: провайдер не должен вызываться при отказе по данным."""

    def __init__(self):
        self.inner = demo_llm()
        self.provider, self.model = self.inner.provider, self.inner.model
        self.calls = 0

    def chat(self, messages, tools=(), *, max_tokens, timeout_s):
        self.calls += 1
        return self.inner.chat(messages, tools, max_tokens=max_tokens, timeout_s=timeout_s)


def _serve(server):
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _stop(*pairs):
    for server, thread in pairs:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def stack(decision_cls=DecisionService, llm=None):
    """Три процесса стека в потоках на свободных портах с реальными HTTP-соединениями между ними."""
    data = _serve(ServiceHTTPServer(("127.0.0.1", 0), make_handler(DataService(ROOT).routes(), None, "data-service")))
    response_model, sha = load_response_model_with_digest(ROOT, ROOT / "artifacts")
    decision_service = decision_cls(
        f"http://127.0.0.1:{data[0].server_port}", "http://127.0.0.1:1", timeout_s=60,
        decision_factory=build_decision_factory(SCRIPTED, dotenv_path=ROOT / ".env", llm=llm),
        response_model=response_model, provenance=loaded_provenance(ROOT, ROOT / "artifacts", sha))
    decision = _serve(ServiceHTTPServer(("127.0.0.1", 0), make_handler(decision_service.routes(), None,
                                                                        "decision-service")))
    gateway_service = GatewayService(f"http://127.0.0.1:{data[0].server_port}",
                                     f"http://127.0.0.1:{decision[0].server_port}", timeout_s=60, root=ROOT)
    gateway = _serve(ServiceHTTPServer(("127.0.0.1", 0), make_gateway_handler(gateway_service)))
    return gateway[0], (gateway, decision, data), decision_service


def get_json(server, path):
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=300)
    connection.request("GET", path, headers={"X-Request-ID": "contract-json"})
    response = connection.getresponse()
    payload = json.loads(response.read())
    connection.close()
    return response.status, payload


def sse_frames(server, path, request_id="contract-sse", on_frame=None):
    """Кадры SSE по мере прихода (не после закрытия): (event, data)."""
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=300)
    connection.request("GET", path, headers={"X-Request-ID": request_id})
    response = connection.getresponse()
    assert response.status == 200 and response.getheader("X-Request-ID") == request_id
    frames, event, data = [], None, []
    while True:
        line = response.fp.readline()
        if not line:
            break
        line = line.decode("utf-8").rstrip("\r\n")
        if line.startswith("event: "):
            event = line[7:]
        elif line.startswith("data: "):
            data.append(line[6:])
        elif not line and event:
            frame = (event, json.loads("\n".join(data)))
            frames.append(frame)
            if on_frame is not None:
                on_frame(frame)
            event, data = None, []
    connection.close()
    return frames


@pytest.fixture
def scripted_agents(monkeypatch):
    """serve и стек с одинаковой scripted-политикой агентов (conftest по умолчанию их выключает)."""
    for key, value in SCRIPTED.items():
        monkeypatch.setenv(key, value)
    agentic_factory._cached_default.cache_clear()
    yield
    agentic_factory._cached_default.cache_clear()


def test_run_meta_and_meaning_match_between_serve_and_stack(scripted_agents):
    serve = make_demo_service(ROOT, 400)
    gateway, servers, decision_service = stack()
    try:
        for query in (RISK, REFUSE):
            local = serve.recompute({k: [v] for k, v in (item.split("=") for item in query.split("&"))})
            status, remote = get_json(gateway, f"/api/decide?{query}")
            assert status == 200 and remote["state"] == local["state"]
            meta, local_meta = remote["run_meta"], local["run_meta"]
            assert meta["conditions_requested"] == local_meta["conditions_requested"]
            assert meta["input_parts"] == local_meta["input_parts"]
            assert meta["input_fingerprint"] == local_meta["input_fingerprint"]
            assert meta["model"] == decision_service.provenance["model"]
            assert meta["model"]["response_model_sha256"] == local_meta["model"]["response_model_sha256"]
            assert meta["code"]["captured"] == "process_start"
            assert remote["decision"]["status"] == local["decision"]["status"]
            assert ((remote["decision"]["selected_plan"] or {}).get("plan_id")
                    == (local["decision"]["selected_plan"] or {}).get("plan_id"))
            assert meta["provider"]["provider"] == local_meta["provider"]["provider"] == "scripted"
        status, remote = get_json(gateway, f"/api/decide?{RISK}")
        decision = remote["decision"]
        assert decision["status"] in {"recommend_scenario", "refuse"}
        if decision["status"] == "refuse":
            # смысл отказа: конкретная причина (фазовая чувствительность парка), а не пустая заглушка;
            # план не выбран и это не противоречит объяснению — см. task-pool.md «Доказательная база 21.09».
            assert decision["refusal"]["kind"] == "tank_phase_sensitive"
            assert decision["tank_estimate"]["failed_taus_h"]
            assert decision["selected_plan"] is None
            assert "фактический уровень" in decision["reason"]
        else:
            assert decision["selected_plan"] is not None
    finally:
        _stop(*servers)


def test_model_facts_come_from_the_computing_process_not_the_gateway_disk():
    class Elsewhere(DecisionService):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.provenance = {"code": {"commit": "decision-process", "dirty": False, "note": None},
                               "model": {"response_model_sha256": "loaded-in-decision",
                                         "training_fingerprint": "decision-training"}}

    gateway, servers, _ = stack(Elsewhere)
    try:
        status, payload = get_json(gateway, "/api/decide?scenario=baseline&snapshot=synthetic")
        assert status == 200
        assert payload["run_meta"]["model"]["response_model_sha256"] == "loaded-in-decision"
        assert payload["run_meta"]["code"]["commit"] == "decision-process"
        assert payload["run_meta"]["input_parts"]["model"] == {"response_model_sha256": "loaded-in-decision",
                                                               "training_fingerprint": "decision-training"}
    finally:
        _stop(*servers)


def test_stage_and_agent_events_arrive_live_before_the_screen():
    gateway, servers, _ = stack()
    try:
        frames = sse_frames(gateway, f"/api/stream?{RISK}")
        kinds = [event for event, _ in frames]
        assert kinds[0] == "phase" and kinds[-2:] == ["screen", "end"]
        screen_at = kinds.index("screen")
        stages = {data["stage"] for event, data in frames[:screen_at] if event == "stage"}
        assert {"state", "trust", "candidates", "choice", "gate", "agents"} <= stages
        agents = [data["event"] for event, data in frames[:screen_at] if event == "agent"]
        assert agents and all({"agent", "kind", "seq", "step"} <= set(event) for event in agents)
        assert [event["seq"] for event in agents] == sorted(event["seq"] for event in agents)
        payload = frames[screen_at][1]["payload"]
        assert payload["decision"]["status"] in {"recommend_scenario", "refuse"}
        assert payload["run_meta"]["conditions_requested"]["scenario"] == "sour_crude"
        assert len(payload["decision"]["agentic"]["trace"]) >= len(agents) > 0
    finally:
        _stop(*servers)


def test_relay_is_live_while_the_decision_is_still_computing():
    """Управляемая задержка: расчёт ждёт, пока клиент gateway не увидит его промежуточный этап."""
    release, seen = threading.Event(), {}

    class Held(DecisionService):
        def _decision(self, *args, **kwargs):
            emit("stage", stage="probe", state="done")
            seen["released_by_client"] = release.wait(timeout=30)
            return super()._decision(*args, **kwargs)

    def on_frame(frame):
        if frame[0] == "stage" and frame[1].get("stage") == "probe":
            seen["screen_before_probe"] = "screen" in seen
            release.set()
        if frame[0] == "screen":
            seen["screen"] = True

    gateway, servers, _ = stack(Held)
    try:
        frames = sse_frames(gateway, "/api/stream?scenario=baseline&snapshot=synthetic", on_frame=on_frame)
        assert seen == {"released_by_client": True, "screen_before_probe": False, "screen": True}
        assert [event for event, _ in frames][-2:] == ["screen", "end"]
    finally:
        _stop(*servers)


def test_data_refusal_through_the_stack_has_no_agent_events_and_no_provider_calls():
    llm = CountingLLM()
    gateway, servers, _ = stack(llm=llm)
    try:
        frames = sse_frames(gateway, f"/api/stream?{REFUSE}")
        kinds = [event for event, _ in frames]
        assert "agent" not in kinds and kinds[-2:] == ["screen", "end"]
        payload = frames[-2][1]["payload"]
        assert payload["decision"]["status"] == "refuse"
        assert payload["decision"]["agentic"]["outcome"] == "skipped"
        assert payload["run_meta"]["conditions_requested"]["fault"] == "both_broken"
        assert llm.calls == 0
    finally:
        _stop(*servers)


def test_decision_error_reaches_the_browser_as_failed_without_a_screen():
    class Broken(DecisionService):
        def _decision(self, *args, **kwargs):
            emit("stage", stage="state", state="done")
            raise RuntimeError("расчёт упал на стороне decision")

    gateway, servers, _ = stack(Broken)
    try:
        frames = sse_frames(gateway, "/api/stream?scenario=baseline&snapshot=synthetic")
        kinds = [event for event, _ in frames]
        assert kinds[-1] == "failed" and "screen" not in kinds
        assert "расчёт упал" in frames[-1][1]["message"]
        status, payload = get_json(gateway, "/api/decide?scenario=baseline&snapshot=synthetic")
        assert status == 200 and payload["state"] == "error"
    finally:
        _stop(*servers)


def test_core_preview_arrives_before_the_single_screen_through_the_stack(scripted_agents):
    """P5: gateway передаёт предварительный результат ядра до итога; итог — ровно один."""
    gateway, servers, _ = stack()
    try:
        frames = sse_frames(gateway, f"/api/stream?{RISK}", request_id="p5-core")
        names = [event for event, _ in frames]
        assert names.count("core") == 1 and names.count("screen") == 1 and "failed" not in names
        assert names.index("core") < names.index("screen")
        core = next(data for event, data in frames if event == "core")
        screen = next(data for event, data in frames if event == "screen")["payload"]
        assert core["run_id"] == screen["decision"]["agentic"]["run_id"]
        assert core["schema_version"] == 1
        assert core["phase"] == "preliminary"
        assert core["decision_id"] == screen["decision"]["agentic"]["legacy_decision_id"]
        assert screen["decision"]["agentic"]["terminal"]["kind"] == "completed"
    finally:
        _stop(*servers)
