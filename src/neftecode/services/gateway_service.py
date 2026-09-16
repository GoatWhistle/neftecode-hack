"""Compatibility gateway: old browser API backed by remote services."""
from __future__ import annotations

import argparse
import os
from urllib.parse import parse_qs, urlsplit
import json

from neftecode.presentation.demo import SOURCE_FAULTS, healthy_state, apply_source_failure
from neftecode.presentation.web.server import PAGE, CONTROLS_STYLE, defaults_for, changes_from, DemoServerError
from neftecode.presentation.web.ui import STYLE, RENDER_JS, error_payload, Screen
from .common import RawResponse, ServiceError, ServiceHTTPClient, ServiceSettings, make_handler, serve, encode_json


class GatewayService:
    def __init__(self, data_url="http://127.0.0.1:8766", decision_url="http://127.0.0.1:8768", timeout_s=10.0,
                 decision_timeout_s=660.0):
        self.data_url, self.decision_url = data_url.rstrip("/"), decision_url.rstrip("/")
        self.client = ServiceHTTPClient(timeout_s)
        #: A decision with language model agents takes minutes, not seconds (AGENT_TIMEOUT_SECONDS + margin).
        self.decision_timeout_s = decision_timeout_s

    def scenarios(self, request_id="gateway"):
        return self.client.request("GET", self.data_url + "/v1/scenarios",
                                   headers={"X-Request-ID": request_id}).data["scenarios"]

    def raw(self, name, request_id="gateway"):
        return self.client.request("POST", self.data_url + "/v1/scenarios/get", {"scenario_id": name},
                                   headers={"X-Request-ID": request_id}).data

    def decide(self, values, request_id="gateway"):
        names = self.scenarios(request_id); name = (values.get("scenario") or [names[0]])[0]
        raw = self.raw(name, request_id); fault = (values.get("fault") or ["healthy"])[0]
        if fault not in SOURCE_FAULTS:
            raise DemoServerError(f"Неизвестный отказ источника «{fault}»")
        state = apply_source_failure(healthy_state(), fault)
        changes = changes_from(values, raw)
        env = self.client.request("POST", self.decision_url + "/v1/decisions",
                                  {"scenario": _changed(raw, changes), "state": state, "budget": 400},
                                  timeout_s=self.decision_timeout_s, headers={"X-Request-ID": request_id})
        result = env.data
        screen = Screen(result["decision"], result["explanation"], result["inventories"], result.get("sources", [])).payload()
        screen["defaults"], screen["applied"], screen["injection"] = defaults_for(raw), changes, state.get("injection")
        return screen

    def page(self, name=None, request_id="gateway"):
        try:
            names = self.scenarios(request_id); chosen = name if name in names else names[0]
            payload = self.decide({"scenario": [chosen]}, request_id)
        except Exception as exc:
            names, chosen = [], name
            payload = {**error_payload(str(exc)), "defaults": {}}
        options = "".join(f'<option value="{n}"{" selected" if n == chosen else ""}>{n}</option>' for n in names)
        faults = "".join(f'<option value="{f}">{f}</option>' for f in SOURCE_FAULTS)
        return PAGE.replace("__STYLE__", STYLE).replace("__CONTROLS_STYLE__", CONTROLS_STYLE).replace("__RENDER_JS__", RENDER_JS).replace("__SCENARIOS__", options).replace("__FAULTS__", faults).replace("__PAYLOAD__", json.dumps(payload, ensure_ascii=False, default=str))

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
        return {"/v1/capabilities": lambda _r: {"service": "gateway-service", "legacy_api": True},
                "/api/scenarios": legacy(lambda r: {"scenarios": self.scenarios(r.request_id)}),
                "/api/defaults": legacy(lambda r: defaults_for(self.raw((r.query.get("scenario") or [self.scenarios(r.request_id)[0]])[0], r.request_id))),
                "/api/decide": legacy(lambda r: self.decide(r.query, r.request_id)) ,
                "/": lambda r: RawResponse(self.page((r.query.get("scenario") or [None])[0], r.request_id).encode(), "text/html; charset=utf-8"),
                "/index.html": lambda r: RawResponse(self.page((r.query.get("scenario") or [None])[0], r.request_id).encode(), "text/html; charset=utf-8")}


def _changed(raw, changes):
    import copy
    from neftecode.presentation.demo import apply_change
    value = copy.deepcopy(raw)
    for change in changes: value = apply_change(value, change["change"], change.get("value"), change.get("target"))
    return value


def make_gateway_handler(service: GatewayService, settings: ServiceSettings | None = None):
    return make_handler(service.routes(), service.ready, service_name="gateway-service", settings=settings)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Нефтекод gateway service")
    parser.add_argument("--host", default=None); parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--data-url", default=None); parser.add_argument("--decision-url", default=None)
    args = parser.parse_args(argv); env = ServiceSettings.from_env("NEFTECODE_GATEWAY_", ServiceSettings(port=8765))
    settings = ServiceSettings(host=args.host or env.host, port=args.port or env.port,
                                request_timeout_s=env.request_timeout_s, shutdown_timeout_s=env.shutdown_timeout_s,
                                max_workers=env.max_workers, max_body_bytes=env.max_body_bytes,
                                max_response_bytes=env.max_response_bytes)
    service = GatewayService(args.data_url or os.getenv("NEFTECODE_DATA_URL", "http://127.0.0.1:8766"),
                             args.decision_url or os.getenv("NEFTECODE_DECISION_URL", "http://127.0.0.1:8768"), settings.request_timeout_s,
                             float(os.getenv("NEFTECODE_GATEWAY_DECISION_TIMEOUT_S", "660")))
    return serve(service.routes(), settings, service.ready, "gateway-service")


if __name__ == "__main__": main()
