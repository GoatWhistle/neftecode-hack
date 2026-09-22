from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any, Mapping

from neftecode.application.contracts import LiveAdviceCommand, LiveForecast, LiveSnapshot
from neftecode.application.services.robustness import RobustnessCheck
from neftecode.application.use_cases.advise_under_conditions import AdviseUnderConditions, report_advice
from neftecode.application.use_cases.get_live_advice import GetLiveAdvice
from neftecode.infrastructure.agentic import build_decision_factory
from neftecode.infrastructure.config.scenario import ScenarioError, parse_scenario
from neftecode.application.ports.live import ForecastBindingError
from neftecode.infrastructure.artifacts.provenance import loaded_provenance
from neftecode.infrastructure.live.advisor import LocalForecastScenarioBinder
from neftecode.infrastructure.live.response_model import load_response_model_with_digest
from neftecode.presentation.web.progress import decision_stream
from neftecode.infrastructure.live.snapshots import bind_snapshot, select_forecast_dict
from neftecode.application.services.tank_estimate import default_tank_estimate_factory
from neftecode.domain.advisory.optimizer import DEFAULT_BUDGET
from neftecode.application.history.moment import assemble_snapshot, check_moment
from neftecode.application.history.time import HistoryError
from .common import Request, ServiceError, ServiceHTTPClient, ServiceSettings, StreamResponse, serve, clean

UNKNOWN_PROVENANCE = {"code": None, "model": None}


class HTTPScenarioProvider:
    def __init__(self, client: ServiceHTTPClient, url: str, headers: Mapping[str, str]):
        self.client = client
        self.url = url
        self.headers = headers

    def get(self, scenario_id: str):
        raw = self.client.request(
            "POST",
            self.url + "/v1/scenarios/get",
            {"scenario_id": scenario_id},
            headers=self.headers,
        ).data
        if not isinstance(raw, dict):
            raise ServiceError("Data service вернул неполный ответ", 502, "invalid_upstream")
        try:
            return parse_scenario(raw), raw
        except (ScenarioError, ValueError, TypeError) as exc:
            raise ServiceError(str(exc), 422, "scenario_rejected") from exc


class HTTPSnapshotProvider:
    def __init__(self, client: ServiceHTTPClient, url: str, headers: Mapping[str, str]):
        self.client = client
        self.url = url
        self.headers = headers

    def snapshot(self, at: str):
        raw = self.client.request("POST", self.url + "/v1/snapshots", {"at": at}, headers=self.headers).data
        if not isinstance(raw, dict) or not isinstance(raw.get("state"), dict) or not isinstance(raw.get("trust"), dict):
            raise ServiceError("Snapshot не содержит state/trust", 502, "invalid_snapshot")
        try:
            return LiveSnapshot.from_dict(raw)
        except ValueError as exc:
            raise ServiceError(str(exc), 502, "invalid_snapshot") from exc


class HTTPForecastProvider:
    def __init__(self, client: ServiceHTTPClient, url: str, headers: Mapping[str, str]):
        self.client = client
        self.url = url
        self.headers = headers

    def forecast(self, snapshot: LiveSnapshot):
        raw = self.client.request("POST", self.url + "/v1/forecast",
                                  {"snapshot": snapshot.to_dict(), "fallback": snapshot.trust.get("fallback", False)},
                                  headers=self.headers).data
        if not isinstance(raw, dict):
            raise ServiceError("Model service вернул неполный ответ", 502, "invalid_upstream")
        try:
            result = LiveForecast.from_dict(raw)
        except ValueError as exc:
            raise ServiceError(str(exc), 502, "invalid_upstream") from exc
        if not result.available:
            raise ServiceError("Прогноз недоступен", 503, "model_unavailable", retryable=True)
        return result


class DecisionService:
    def __init__(self, data_url: str = "http://127.0.0.1:8766", model_url: str = "http://127.0.0.1:8767",
                 timeout_s: float = 10.0, decision_factory=None, response_model: dict | None = None,
                 provenance: dict | None = None):
        self.data_url, self.model_url = data_url.rstrip("/"), model_url.rstrip("/")
        self.client = ServiceHTTPClient(timeout_s)
        self.decision_factory = decision_factory
        self.response_model = response_model
        # Происхождение закреплено вместе с загруженной моделью: сообщается процессом, который считает.
        self.provenance = provenance or UNKNOWN_PROVENANCE

    @staticmethod
    def _body(request: Request) -> dict[str, Any]:
        if not isinstance(request.body, dict):
            raise ServiceError("Тело запроса должно быть JSON-объектом", 400, "invalid_body")
        return request.body

    def _decision(self, raw: dict, state: dict | None, budget: int, trust_cfg: dict | None = None,
                  trust_origin: str | None = None, snapshot: dict | None = None) -> dict:
        trust_cfg = trust_cfg or {}
        if not isinstance(budget, int) or isinstance(budget, bool) or budget <= 0:
            raise ServiceError("budget должен быть положительным целым", 422, "invalid_budget")
        try:
            advice = AdviseUnderConditions(
                parse_scenario, bind_snapshot, select_forecast_dict,
                self.decision_factory, default_tank_estimate_factory,
            ).execute(raw, state or {}, budget, trust_cfg, snapshot, self.response_model)
        except (ScenarioError, ForecastBindingError, ValueError, TypeError) as exc:
            raise ServiceError(str(exc), 422, "scenario_rejected") from exc
        report_advice(advice)
        return {"decision": clean(advice["decision"]), "explanation": clean(advice["explanation"]),
                "inventories": clean(advice["inventories"]),
                "sources": [clean(source.to_dict()) for source in advice["trust"].sources.values()],
                "trust_origin": trust_origin,
                "binding": clean(advice["binding"]),
                "provenance": clean(self.provenance)}

    def _decision_request(self, request: Request) -> tuple:
        body = self._body(request)
        raw, state = body.get("scenario"), body.get("state")
        if not isinstance(raw, dict):
            raise ServiceError("Нужно передать scenario", 400, "invalid_scenario")
        if state is not None and not isinstance(state, dict):
            raise ServiceError("state должен быть JSON-объектом", 400, "invalid_state")
        trust_cfg, trust_origin = body.get("trust_config"), body.get("trust_origin")
        if trust_cfg is not None and not isinstance(trust_cfg, dict):
            raise ServiceError("trust_config должен быть JSON-объектом", 400, "invalid_trust_config")
        if trust_origin is not None and not isinstance(trust_origin, str):
            raise ServiceError("trust_origin должен быть строкой", 400, "invalid_trust_origin")
        snapshot = body.get("snapshot")
        if snapshot is not None and (not isinstance(snapshot, dict) or not isinstance(snapshot.get("forecast"), dict)):
            raise ServiceError("snapshot должен быть JSON-объектом среза с полем forecast", 400, "invalid_snapshot")
        return raw, state, body.get("budget", DEFAULT_BUDGET), trust_cfg, trust_origin, snapshot

    def decide(self, request: Request):
        return self._decision(*self._decision_request(request))

    def decide_stream(self, request: Request):
        """Тот же расчёт, что /v1/decisions, но этапы и события агентов уходят клиенту по мере появления.

        Формат — SSE того же вида, что у /api/stream: phase/stage/agent/tick, затем screen c результатом
        или failed. Запрос проверяется до открытия потока, поэтому ошибки входа остаются JSON-ошибками.
        Разрыв соединения клиентом отменяет расчёт через токен отмены.
        """
        arguments = self._decision_request(request)
        return StreamResponse(frame.encode() for frame in decision_stream(lambda: self._decision(*arguments)))

    def live(self, request: Request):
        body = self._body(request)
        at, scenario_id = body.get("at"), body.get("scenario_id")
        if not isinstance(at, str) or not at.strip() or not isinstance(scenario_id, str) or not scenario_id:
            raise ServiceError("Нужны at и scenario_id", 400, "invalid_live_request")
        budget = body.get("budget", DEFAULT_BUDGET)
        headers = {"X-Request-ID": request.request_id or "unknown"}
        advice = GetLiveAdvice(
            scenarios=HTTPScenarioProvider(self.client, self.data_url, headers),
            snapshots=HTTPSnapshotProvider(self.client, self.data_url, headers),
            forecasts=HTTPForecastProvider(self.client, self.model_url, headers),
            binder=LocalForecastScenarioBinder(self.response_model),
            robustness_factory=lambda scenario, raw: RobustnessCheck(scenario, raw, scenario_parser=parse_scenario),
            decision_factory=self.decision_factory,
            tank_estimate_factory=default_tank_estimate_factory,
            scenario_parser=parse_scenario,
        )
        if not isinstance(budget, int) or isinstance(budget, bool) or budget <= 0:
            raise ServiceError("budget должен быть положительным целым", 422, "invalid_budget")
        result = advice.execute(LiveAdviceCommand(at=at, scenario_id=scenario_id, budget=budget))
        if result.error_kind is not None:
            raise ServiceError(result.error or "Ошибка связывания прогноза", 422, result.error_kind)
        payload = result.to_dict()
        payload["inventories"] = dict(result.inventories)
        payload["sources"] = list(result.trust.get("sources", {}).values())
        return clean(payload)

    def history_coverage(self, request_id: str = "history") -> dict[str, Any]:
        """Период, где произвольный момент допустим: телеметрия data-service ∩ доступность модели."""
        headers = {"X-Request-ID": request_id}
        data = self.client.request("GET", self.data_url + "/v1/history/coverage", headers=headers).data
        if not isinstance(data, dict) or data.get("available") is not True:
            return {"available": False, "reason": (data or {}).get("reason") or "Телеметрия не поставлена"}
        try:
            models = self.client.request("GET", self.model_url + "/v1/models", headers=headers).data
        except ServiceError as exc:
            return {"available": False, "reason": f"Модель прогноза недоступна: {exc}"}
        if not isinstance(models, dict) or not isinstance(models.get("valid_from"), str):
            return {"available": False, "reason": "Model-service не сообщил доступность модели"}
        return {"available": True, "reason": None, "start": data["start"], "end": data["end"],
                "model_valid_from": models["valid_from"], "model_fingerprint": models.get("fingerprint")}

    def history_prepare(self, request: Request):
        """Одно причинное состояние момента и две ветви прогноза на одном snapshot_id (P4).
        Решение здесь не считается и LLM не вызывается: срез идёт в обычный /v1/decisions."""
        body = self._body(request)
        at = body.get("at")
        headers = {"X-Request-ID": request.request_id or "history"}
        coverage = self.history_coverage(request.request_id or "history")
        if not coverage.get("available"):
            raise ServiceError(coverage.get("reason") or "История недоступна", 503, "measurements_unavailable")
        try:
            check_moment(at, coverage)
        except HistoryError as exc:
            raise ServiceError(str(exc), 422, exc.code) from exc
        data = self.client.request("POST", self.data_url + "/v1/snapshots", {"at": at}, headers=headers).data
        if not isinstance(data, dict) or not isinstance(data.get("state"), dict) or not isinstance(data.get("trust"), dict):
            raise ServiceError("Snapshot не содержит state/trust", 502, "invalid_snapshot")
        usable = data["trust"].get("usable") is True
        if usable:
            forecast, fallback = (self.client.request("POST", self.model_url + "/v1/forecast",
                                                      {"snapshot": data, "fallback": branch}, headers=headers).data
                                  for branch in (False, True))
        else:
            forecast = fallback = {"model": None, "value": None, "lower": None, "upper": None, "available": False,
                                   "reason": "Прогноз не запрашивался: источники на этот момент непригодны"}
        snapshot = assemble_snapshot(data, forecast, fallback, coverage.get("model_fingerprint"))
        exclusions = self.client.request("POST", self.data_url + "/v1/history/exclusions",
                                         {"start": at, "end": at}, headers=headers).data
        return clean({"snapshot": snapshot, "exclusions": exclusions, "trust_usable": usable,
                      "coverage": {k: coverage[k] for k in ("start", "end", "model_valid_from")},
                      "provenance": {"data_snapshot_id": data.get("snapshot_id"),
                                     "feature_schema_hash": data.get("feature_schema_hash"),
                                     "model_fingerprint": coverage.get("model_fingerprint"),
                                     "timezone": "source-local",
                                     "prepared_by": "decision-service: data-service state + model-service forecasts"},
                      "preparation": "one state, two frozen forecast branches; no decision or LLM"})

    def capabilities(self, _request):
        return {"service": "decision-service", "decisions": True, "live_advice": True,
                "dependencies": {"data": self.data_url, "model": self.model_url}}

    def ready(self):
        for url in (self.data_url + "/readyz", self.model_url + "/readyz"):
            try:
                self.client.request("GET", url)
            except ServiceError:
                return False
        return True

    def routes(self):
        return {"/v1/decisions": self.decide, "/v1/decisions/stream": self.decide_stream,
                "/v1/live/advice": self.live,
                "/v1/history/coverage": lambda request: self.history_coverage(request.request_id or "history"),
                "/v1/history/prepare": self.history_prepare,
                "/v1/capabilities": self.capabilities}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Нефтекод decision service")
    parser.add_argument("--host", default=None); parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--data-url", default=None); parser.add_argument("--model-url", default=None)
    parser.add_argument("--root", type=Path, default=None, help="Корень проекта с artifacts/response_model.json")
    parser.add_argument("--artifacts", type=Path, default=None, help="Каталог артефактов (response_model.json)")
    args = parser.parse_args(argv)
    root = Path(args.root or os.getenv("NEFTECODE_ROOT", "."))
    artifacts = args.artifacts if args.artifacts is not None else root / "artifacts"
    env = ServiceSettings.from_env("NEFTECODE_DECISION_", ServiceSettings(port=8768))
    settings = ServiceSettings(host=args.host or env.host, port=args.port or env.port,
                                request_timeout_s=env.request_timeout_s, shutdown_timeout_s=env.shutdown_timeout_s,
                                max_workers=env.max_workers, max_body_bytes=env.max_body_bytes,
                                max_response_bytes=env.max_response_bytes)
    response_model, response_sha256 = load_response_model_with_digest(root, artifacts)
    service = DecisionService(args.data_url or os.getenv("NEFTECODE_DATA_URL", "http://127.0.0.1:8766"),
                              args.model_url or os.getenv("NEFTECODE_MODEL_URL", "http://127.0.0.1:8767"),
                              settings.request_timeout_s, decision_factory=build_decision_factory(dotenv_path=root / ".env"),
                              response_model=response_model,
                              provenance=loaded_provenance(root, artifacts, response_sha256))
    return serve(service.routes(), settings, service.ready, "decision-service")


if __name__ == "__main__":
    main()
