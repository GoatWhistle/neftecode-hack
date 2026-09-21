from __future__ import annotations

import argparse
from collections.abc import Mapping
import os
from pathlib import Path

from neftecode.application.conditions import (SOURCE_FAULTS, apply_changes, canonical_conditions, changes_from,
                                               defaults_for, state_under)
from neftecode.presentation.demo import snapshot_key, snapshot_title, state_origin_label
from neftecode.application.services.trust import DataTrustAgent
from neftecode.application.ports import SnapshotRepository
from neftecode.infrastructure.live.snapshots import select_forecast_dict
from neftecode.infrastructure.scenarios import FileSnapshotRepository, HttpScenarioRepository
from neftecode.presentation.web.cache import DecisionCache, cache_key
from neftecode.presentation.web.query import DemoServerError, parse_conditions
from neftecode.presentation.web.server import FIRST_SNAPSHOT
from neftecode.presentation.web.static import StaticError, StaticFiles, resolve_static_dir
from neftecode.presentation.web.ui import error_payload, Screen
from neftecode.presentation.web.progress import decision_stream
from neftecode.infrastructure.config.trust_rules import load_trust_rules
from neftecode.infrastructure.llm.config import decision_wait_seconds
from neftecode.domain.advisory.optimizer import DEFAULT_BUDGET
from .common import (RawResponse, ServiceError, ServiceHTTPClient, ServiceSettings, StreamResponse,
                     make_handler, serve, encode_json)


class StaticRoutes(Mapping):
    def __init__(self, api: dict, fallback):
        self.api = dict(api)
        self.fallback = fallback

    def __getitem__(self, key):
        if key in self.api:
            return self.api[key]
        if key.startswith("/api/") or key.startswith("/v1/"):
            raise KeyError(key)
        return self.fallback

    def __iter__(self):
        return iter(self.api)

    def __len__(self) -> int:
        return len(self.api)

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default


class GatewayService:
    def __init__(self, data_url="http://127.0.0.1:8766", decision_url="http://127.0.0.1:8768", timeout_s=10.0,
                 decision_timeout_s=660.0, root: str | Path = ".", artifacts: str | Path | None = None,
                 static: str | Path | None = None, scenario_repository: HttpScenarioRepository | None = None,
                 snapshot_repository: SnapshotRepository | None = None):
        self.data_url, self.decision_url = data_url.rstrip("/"), decision_url.rstrip("/")
        self.client = ServiceHTTPClient(timeout_s)
        self.decision_timeout_s = decision_timeout_s
        root = Path(root)
        out = Path(artifacts) if artifacts is not None else root / "artifacts"
        self.trust_cfg, self.trust_origin = load_trust_rules(root, out)
        self.scenario_repository = scenario_repository or HttpScenarioRepository(self.client, self.data_url)
        self.snapshots = (snapshot_repository or FileSnapshotRepository(out)).all()
        self.cache = DecisionCache()
        self.static = StaticFiles(resolve_static_dir(root, static))

    def snapshot_options(self):
        options = [(snapshot_key(item), snapshot_title(item)) for item in reversed(self.snapshots)]
        options.append(("synthetic", "синтетическое состояние сценария"))
        chosen = self.default_snapshot()
        return [o for o in options if o[0] == chosen] + [o for o in options if o[0] != chosen]

    def default_snapshot(self):
        keys = [snapshot_key(item) for item in reversed(self.snapshots)] + ["synthetic"]
        return FIRST_SNAPSHOT if FIRST_SNAPSHOT in keys else keys[0]

    def snapshot(self, name):
        if name in (None, "", "synthetic"):
            return None
        for item in self.snapshots:
            if snapshot_key(item) == name or item.get("label") == name:
                return item
        raise DemoServerError(f"Срез «{name}» не найден")

    def scenarios(self, request_id="gateway"):
        return self.scenario_repository.for_request(request_id).names()

    def raw(self, name, request_id="gateway"):
        return self.scenario_repository.for_request(request_id).raw(name)

    def decide(self, values, request_id="gateway"):
        names = self.scenarios(request_id); name = (values.get("scenario") or [names[0]])[0]
        raw = self.raw(name, request_id)
        default_snapshot = self.default_snapshot()
        canonical = canonical_conditions(parse_conditions(values), raw, name, default_snapshot)
        return self.cache.get(cache_key(canonical), lambda: self._decide(canonical, raw, request_id))

    def stream(self, values, request_id="gateway"):
        names = self.scenarios(request_id); name = (values.get("scenario") or [names[0]])[0]
        raw = self.raw(name, request_id)
        canonical = canonical_conditions(parse_conditions(values), raw, name, self.default_snapshot())

        def compute():
            payload = self._decide(canonical, raw, request_id)
            self.cache.put(cache_key(canonical), payload)
            return payload

        return StreamResponse((frame.encode() for frame in decision_stream(compute)))

    def _decide(self, canonical, raw, request_id):
        chosen = self.snapshot(canonical["snapshot"])
        state = state_under(chosen, canonical["fault"])
        changes = changes_from(canonical, raw)
        env = self.client.request("POST", self.decision_url + "/v1/decisions",
                                  {"scenario": apply_changes(raw, changes), "state": state,
                                   "budget": DEFAULT_BUDGET,
                                   "trust_config": self.trust_cfg, "trust_origin": self.trust_origin,
                                   "snapshot": chosen},
                                  timeout_s=self.decision_timeout_s, headers={"X-Request-ID": request_id})
        result = env.data
        active_forecast = (select_forecast_dict(chosen, DataTrustAgent(self.trust_cfg).assess(state))
                           if chosen is not None else None)
        screen = Screen(result["decision"], result["explanation"], result["inventories"], result.get("sources", []),
                        rule_origin=result.get("trust_origin", self.trust_origin),
                        state_origin=state_origin_label(state, chosen),
                        decision_time=state.get("decision_time"),
                        forecast=active_forecast,
                        forecast_used=((result.get("binding") or {}).get("measurement_binding") is not None)
                        if chosen is not None else None).payload()
        screen["defaults"], screen["applied"], screen["injection"] = defaults_for(raw), changes, state.get("injection")
        screen["snapshot"], screen["binding"] = (snapshot_key(chosen) if chosen is not None else None), result.get("binding")
        screen["decision_timeout_s"] = self.decision_timeout_s
        return screen

    def options_payload(self, name=None, request_id="gateway"):
        try:
            names = self.scenarios(request_id); chosen = name if name in names else names[0]
            payload = {"state": "loading", "message": "Считаем решение для выбранных условий…",
                       "defaults": defaults_for(self.raw(chosen, request_id)), "scenario": chosen,
                       "snapshot": self.default_snapshot(), "decision_timeout_s": self.decision_timeout_s}
        except Exception as exc:
            names = []
            payload = {**error_payload(str(exc)), "defaults": {}}
        payload["scenarios"] = names
        payload["faults"] = list(SOURCE_FAULTS)
        payload["snapshots"] = [{"key": key, "title": title} for key, title in self.snapshot_options()]
        return payload

    def asset(self, path):
        try:
            asset = self.static.asset(path)
        except StaticError as exc:
            return RawResponse(encode_json({"error": str(exc)}), "application/json; charset=utf-8", 404)
        return RawResponse(asset.body, asset.content_type)

    def ready(self):
        for url in (self.data_url + "/readyz", self.decision_url + "/readyz"):
            try: self.client.request("GET", url)
            except ServiceError: return False
        return True

    def routes(self):
        def legacy(call):
            def route(request):
                try:
                    return RawResponse(encode_json(call(request)), "application/json; charset=utf-8")
                except Exception as exc:
                    return RawResponse(encode_json({**error_payload(str(exc)), "defaults": {}}),
                                       "application/json; charset=utf-8", 200)
            return route
        api = {"/v1/capabilities": lambda _r: {"service": "gateway-service", "legacy_api": True},
                "/api/scenarios": legacy(lambda r: {"scenarios": self.scenarios(r.request_id)}),
                "/api/defaults": legacy(lambda r: defaults_for(self.raw((r.query.get("scenario") or [self.scenarios(r.request_id)[0]])[0], r.request_id))),
                "/api/decide": legacy(lambda r: self.decide(r.query, r.request_id)),
                "/api/stream": lambda r: self.stream(r.query, r.request_id),
                "/api/options": legacy(lambda r: self.options_payload((r.query.get("scenario") or [None])[0], r.request_id)),
                "/": lambda r: self.asset("/")}
        return StaticRoutes(api, lambda r: self.asset(r.path))


def make_gateway_handler(service: GatewayService, settings: ServiceSettings | None = None):
    return make_handler(service.routes(), service.ready, service_name="gateway-service", settings=settings)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Нефтекод gateway service")
    parser.add_argument("--host", default=None); parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--data-url", default=None); parser.add_argument("--decision-url", default=None)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--artifacts", type=Path, default=Path("artifacts"))
    parser.add_argument("--static", type=Path, default=None)
    args = parser.parse_args(argv); env = ServiceSettings.from_env("NEFTECODE_GATEWAY_", ServiceSettings(port=8765))
    settings = ServiceSettings(host=args.host or env.host, port=args.port or env.port,
                                request_timeout_s=env.request_timeout_s, shutdown_timeout_s=env.shutdown_timeout_s,
                                max_workers=env.max_workers, max_body_bytes=env.max_body_bytes,
                                max_response_bytes=env.max_response_bytes)
    service = GatewayService(args.data_url or os.getenv("NEFTECODE_DATA_URL", "http://127.0.0.1:8766"),
                             args.decision_url or os.getenv("NEFTECODE_DECISION_URL", "http://127.0.0.1:8768"), settings.request_timeout_s,
                             float(os.getenv("NEFTECODE_GATEWAY_DECISION_TIMEOUT_S") or decision_wait_seconds(args.root)),
                             root=args.root, artifacts=args.artifacts, static=args.static)
    return serve(service.routes(), settings, service.ready, "gateway-service")


if __name__ == "__main__": main()
