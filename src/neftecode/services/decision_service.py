"""HTTP process owning scenario decisions and live advice orchestration."""
from __future__ import annotations

import argparse
import os
from typing import Any, Mapping

from neftecode.application.services.explain import explain
from neftecode.application.services.trust import DataTrustAgent
from neftecode.application.contracts import LiveAdviceCommand, LiveForecast, LiveSnapshot
from neftecode.application.use_cases.get_live_advice import GetLiveAdvice
from neftecode.application.use_cases.make_decision import MakeDecision
from neftecode.domain.production.inventory import initial_state
from neftecode.infrastructure.config.scenario import ScenarioError, parse_scenario
from neftecode.infrastructure.live.advisor import LocalForecastScenarioBinder
from neftecode.evaluation.robustness import RobustnessCheck
from .common import Request, ServiceError, ServiceHTTPClient, ServiceSettings, serve, clean


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
                 timeout_s: float = 10.0):
        self.data_url, self.model_url = data_url.rstrip("/"), model_url.rstrip("/")
        self.client = ServiceHTTPClient(timeout_s)

    @staticmethod
    def _body(request: Request) -> dict[str, Any]:
        if not isinstance(request.body, dict):
            raise ServiceError("Тело запроса должно быть JSON-объектом", 400, "invalid_body")
        return request.body

    @staticmethod
    def _decision(raw: dict, state: dict | None, budget: int) -> dict:
        try:
            scenario = parse_scenario(raw)
        except (ScenarioError, ValueError, TypeError) as exc:
            raise ServiceError(str(exc), 422, "scenario_rejected") from exc
        if not isinstance(budget, int) or isinstance(budget, bool) or budget <= 0:
            raise ServiceError("budget должен быть положительным целым", 422, "invalid_budget")
        decision = MakeDecision(scenario, robustness_evaluator=RobustnessCheck(
            scenario, raw, scenario_parser=parse_scenario)).decide(
                state=state or {}, budget=budget, raw_scenario=raw)
        trust = DataTrustAgent({}).assess(state or {})
        return {"decision": clean(decision), "explanation": clean(explain(decision, scenario)),
                "inventories": {key: value.inventory_t for key, value in initial_state(scenario).items()},
                "sources": [clean(source.to_dict()) for source in trust.sources.values()]}

    def decide(self, request: Request):
        body = self._body(request)
        raw, state = body.get("scenario"), body.get("state")
        if not isinstance(raw, dict):
            raise ServiceError("Нужно передать scenario", 400, "invalid_scenario")
        if state is not None and not isinstance(state, dict):
            raise ServiceError("state должен быть JSON-объектом", 400, "invalid_state")
        return self._decision(raw, state, body.get("budget", 400))

    def live(self, request: Request):
        body = self._body(request)
        at, scenario_id = body.get("at"), body.get("scenario_id")
        if not isinstance(at, str) or not at.strip() or not isinstance(scenario_id, str) or not scenario_id:
            raise ServiceError("Нужны at и scenario_id", 400, "invalid_live_request")
        budget = body.get("budget", 400)
        headers = {"X-Request-ID": request.request_id or "unknown"}
        advice = GetLiveAdvice(
            scenarios=HTTPScenarioProvider(self.client, self.data_url, headers),
            snapshots=HTTPSnapshotProvider(self.client, self.data_url, headers),
            forecasts=HTTPForecastProvider(self.client, self.model_url, headers),
            binder=LocalForecastScenarioBinder(),
            robustness_factory=lambda scenario, raw: RobustnessCheck(scenario, raw, scenario_parser=parse_scenario),
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
        return {"/v1/decisions": self.decide, "/v1/live/advice": self.live,
                "/v1/capabilities": self.capabilities}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Нефтекод decision service")
    parser.add_argument("--host", default=None); parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--data-url", default=None); parser.add_argument("--model-url", default=None)
    args = parser.parse_args(argv)
    env = ServiceSettings.from_env("NEFTECODE_DECISION_", ServiceSettings(port=8768))
    settings = ServiceSettings(host=args.host or env.host, port=args.port or env.port,
                                request_timeout_s=env.request_timeout_s, shutdown_timeout_s=env.shutdown_timeout_s,
                                max_workers=env.max_workers, max_body_bytes=env.max_body_bytes,
                                max_response_bytes=env.max_response_bytes)
    service = DecisionService(args.data_url or os.getenv("NEFTECODE_DATA_URL", "http://127.0.0.1:8766"),
                              args.model_url or os.getenv("NEFTECODE_MODEL_URL", "http://127.0.0.1:8767"),
                              settings.request_timeout_s)
    return serve(service.routes(), settings, service.ready, "decision-service")


if __name__ == "__main__":
    main()
