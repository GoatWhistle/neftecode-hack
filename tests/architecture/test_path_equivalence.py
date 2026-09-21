"""Z4 (task-pool.md, дефекты A/C/#1): один и тот же срез+условие через demo, gateway и live.

Три входа в систему обязаны давать одно и то же решение на одинаковых условиях:

  * demo        -> neftecode.composition.decision.run_demo_decision (presentation.demo.Demo.run)
  * gateway     -> GatewayService._decide -> HTTP /v1/decisions -> DecisionService._decision
                   -> neftecode.infrastructure.live.snapshots.bind_snapshot
  * live        -> DecisionService.live() -> GetLiveAdvice.execute -> HTTPForecastProvider

demo и gateway разделяют один и тот же bind_snapshot(): он ре-оценивает доверие к
источникам по текущему state, но НЕ пересчитывает прогноз — форекаст всегда берётся
как есть из snapshot["forecast"], то есть из значения, вычисленного на момент сборки
среза (до инъекции отказа). Путь live запрашивает прогноз заново через
ForecastProvider.forecast(snapshot), передавая туда пересчитанный trust.fallback,
поэтому именно live обязан переключиться на no-PAK модель, когда ПАК более не
доверенный источник.

Ожидание по `context/agent-prompt.md` (доказательная база 21.09, срез 2026-07-24T03:00 +
frozen_pak): демо считает по недоверенному ПАК (`last_pak_bc` 14.93/20.94) и предлагает
изменение режима; корректный путь обязан переключиться на `catboost_no_pak` (8.11/11.09) и
дать hold. Ниже — тест, который прогоняет один и тот же срез+условие через все три пути и
фиксирует конкретное расхождение: demo и gateway сходятся друг с другом на неверном
прогнозе, а live (пересчитывающий прогноз) расходится с ними обоими.

Тест ДОЛЖЕН быть красным: это фиксация известного дефекта #1, а не проверка починки.
"""
import json
import threading
from http.client import HTTPConnection
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from neftecode.bootstrap import run_demo_decision
from neftecode.infrastructure.config.trust_rules import load_trust_rules
from neftecode.infrastructure.live.snapshots import write_snapshot
from neftecode.application.conditions import apply_source_failure
from neftecode.presentation.demo import Demo, snapshot_key
from neftecode.services.common import Request, ServiceHTTPServer, make_handler
from neftecode.services.data_service import DataService
from neftecode.services.decision_service import DecisionService
from neftecode.services.gateway_service import GatewayService, make_gateway_handler

ROOT = Path(__file__).resolve().parents[2]
BASELINE = json.loads((ROOT / "config/scenarios/baseline.json").read_text(encoding="utf-8"))
AT = "2026-07-24T03:00:00"

# Значения из доказательной базы 21.09 (context/agent-prompt.md, строка 198-200):
# недоверенный ПАК даёт last_pak_bc 14.93/20.94, корректный пересчёт без ПАК -
# catboost_no_pak 8.11/11.09.
WRONG_FORECAST = {"model": "last_pak_bc", "value": 14.93, "lower": 10.62, "upper": 20.94,
                  "available": True, "reason": "тест Z4: прогноз по недоверенному ПАК"}
CORRECT_FORECAST = {"model": "catboost_no_pak", "value": 8.11, "lower": 6.31, "upper": 11.09,
                    "available": True, "reason": "тест Z4: пересчёт без ПАК после отказа источника"}


def real_state(decision_time=AT, t6=367.8):
    when = pd.Timestamp(decision_time)
    return {"decision_time": decision_time, "origin": "real_measurements_at_decision_time",
            "lab_value": 6.8, "lab_age_hours": 14.0, "lab_usable": True,
            "pak_value": 5.88, "pak_age_minutes": 0.0, "pak_usable": True, "pak_frozen": False,
            "pak_conflict": False, "telemetry_missing_fraction": 0.0,
            "pak_last_trusted_value": 5.88, "pak_last_trusted_time": decision_time,
            "quality_history_hours": 72, "pak_expected_per_hour": 6.0,
            "pak_trusted_hourly": [[(when.floor("h") - pd.Timedelta(value=h, unit="h")).isoformat(), 5.0, 6]
                                   for h in range(72)],
            "lab_recent": [],
            "measurements": {"ht.T6": {"value": t6, "time": decision_time, "age_min": 0.0},
                             "ht.F9": {"value": 206.1, "time": decision_time, "age_min": 0.0},
                             "ht.F26": {"value": 244.1, "time": decision_time, "age_min": 0.0}}}


def make_snapshot():
    """Срез 2026-07-24T03:00, собранный, когда ПАК ещё был доверен (как это происходит в
    build_snapshot: forecast зависит от trust на момент сборки среза, а не на момент запроса
    решения)."""
    state = real_state()
    return {"schema_version": "v1", "at": AT, "label": "риск по качеству", "why": "тест Z4",
            "state": state, "trust": {"usable": True, "primary": "ПАК", "fallback": False},
            "forecast": WRONG_FORECAST,
            # I1: резервный прогноз без ПАК, посчитанный на момент сборки среза
            # (forecast_at(..., fallback=True)) — bind_snapshot обязан выбрать его после
            # пересчёта trust.fallback_mode=True (инъекция frozen_pak).
            "forecast_no_pak": CORRECT_FORECAST,
            "measured": state["measurements"], "synthetic_edits": [],
            "model_fingerprint": "fp-z4", "source_rules_fingerprint": None}


def trust_cfg():
    return load_trust_rules(ROOT, ROOT / "nowhere")[0]


def start(service, name, handler_factory=make_handler):
    server = ServiceHTTPServer(("127.0.0.1", 0), handler_factory(service) if handler_factory is make_gateway_handler
                               else handler_factory(service.routes(), service.ready, name))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def http_get(server, path, request_id="z4-equivalence"):
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=20)
    connection.request("GET", path, headers={"X-Request-ID": request_id})
    response = connection.getresponse()
    payload = json.loads(response.read())
    connection.close()
    return response.status, payload


def run_demo_path(snapshot):
    """Путь 1: демо-режим (presentation.demo.Demo -> composition.decision.run_demo_decision)."""
    demo = Demo(BASELINE, run_demo_decision, trust_cfg(), 250, snapshots=[snapshot])
    result = demo.run(fault="frozen_pak", snapshot=snapshot_key(snapshot))
    assert not result["rejected"], f"demo отклонил условия: {result}"
    return result["screen"]


def run_gateway_path(snapshot):
    """Путь 2: HTTP gateway (/api/decide) -> HTTP decision-service (/v1/decisions).

    Реальные HTTP-серверы, как и в проде: gateway ничего не знает про решение, только
    проксирует его через decision-service, который вызывает тот же bind_snapshot, что и demo.
    """
    data, data_thread = start(DataService(ROOT), "data-service")
    decision_service = DecisionService(f"http://127.0.0.1:{data.server_port}", "http://127.0.0.1:1", timeout_s=5)
    decision, decision_thread = start(decision_service, "decision-service")
    gateway_service = GatewayService(f"http://127.0.0.1:{data.server_port}",
                                     f"http://127.0.0.1:{decision.server_port}", timeout_s=20, root=ROOT)
    gateway_service.snapshots = [snapshot]
    gateway, gateway_thread = start(gateway_service, "gateway-service", make_gateway_handler)
    try:
        status, payload = http_get(gateway, f"/api/decide?scenario=baseline&fault=frozen_pak&snapshot={snapshot_key(snapshot)}")
        assert status == 200, payload
        assert "decision" in payload, f"gateway не выдал решение: {payload}"
        return payload
    finally:
        for server, thread in ((gateway, gateway_thread), (decision, decision_thread), (data, data_thread)):
            server.shutdown(); server.server_close(); thread.join(timeout=3)


def run_live_path(snapshot):
    """Путь 3: DecisionService.live() -> GetLiveAdvice, реальный контракт /v1/live/advice.

    В отличие от bind_snapshot, здесь прогноз запрашивается заново через
    ForecastProvider.forecast(snapshot) с пересчитанным trust.fallback: при отказе ПАК
    (frozen_pak) корректный сервис модели обязан вернуть catboost_no_pak, а не эхо старого
    прогноза из среза.
    """
    raw = BASELINE
    faulted_state = apply_source_failure(real_state(), "frozen_pak")
    live_trust = {"usable": True, "primary": "ЛИМС", "fallback": True,
                 "sources": {"ЛИМС": {"name": "ЛИМС", "usable": True, "status": "ok"},
                             "ПАК": {"name": "ПАК", "usable": False, "status": "unusable"}}}

    class Client:
        def request(self, method, url, body=None, headers=None):
            if url.endswith("/v1/scenarios/get"):
                return SimpleNamespace(data=raw)
            if url.endswith("/v1/snapshots"):
                return SimpleNamespace(data={"at": AT, "state": faulted_state, "trust": live_trust})
            if url.endswith("/v1/forecast"):
                # Настоящий model-service выбирает bundle["fallback"] (catboost_no_pak), когда
                # приходит fallback=True; здесь это заменено фиксированным контрактным двойником,
                # так как реальный artifacts/model.pkl в тестовом окружении недоступен.
                assert body["fallback"] is True, "live обязан запросить no-PAK модель при отказе ПАК"
                return SimpleNamespace(data=CORRECT_FORECAST)
            raise AssertionError(f"неожиданный запрос: {url}")

    service = DecisionService(response_model=None)
    service.client = Client()
    result = service.live(Request("POST", "/v1/live/advice", {},
                                  {"at": AT, "scenario_id": "baseline", "budget": 250}))
    assert result["decision"] is not None, f"live отказал: {result}"
    return result


def test_demo_gateway_and_live_agree_on_the_same_slice_and_fault():
    """Z4: demo, gateway и live должны дать одно решение на срезе 2026-07-24T03:00 + frozen_pak.

    Известный факт (context/agent-prompt.md, доказательная база 21.09): сейчас demo и gateway
    сходятся друг с другом на СТАРОМ прогнозе (bind_snapshot не пересчитывает forecast после
    инъекции отказа ПАК), а live, пересчитывающий прогноз заново, обязан дать другой ответ.
    Это и есть дефект #1: три пути НЕ эквивалентны на одинаковых условиях.
    """
    snapshot = make_snapshot()

    demo_screen = run_demo_path(snapshot)
    gateway_screen = run_gateway_path(snapshot)
    live_result = run_live_path(snapshot)

    demo_model = demo_screen["forecast"]["model"]
    gateway_model = gateway_screen["forecast"]["model"]
    live_model = live_result["forecast"]["model"]

    # Проверка согласованности между demo и gateway: оба используют bind_snapshot и должны
    # хотя бы совпадать друг с другом (иначе дефект ещё серьёзнее, чем зафиксировано в пуле).
    #
    # ПРАВКА после I1 (не логика проверки, а фиксация ожидаемого значения): до фикса дефекта #1
    # это сравнение проверяло, что demo и gateway сходятся на СТАРОМ прогнозе WRONG_FORECAST
    # (last_pak_bc) — именно так тест был красным. I1 чинит bind_snapshot и общую точку показа
    # прогноза (composition/decision.py, services/decision_service.py, services/gateway_service.py)
    # так, чтобы demo и gateway тоже пересчитывали прогноз по актуальному trust.fallback_mode —
    # это и есть цель задачи ("общая функция demo и decision-service"), а не расхождение с live.
    # Поэтому после фикса demo и gateway обязаны сойтись друг с другом на ПРАВИЛЬНОМ прогнозе
    # catboost_no_pak, а не остаться на last_pak_bc.
    assert demo_model == gateway_model == CORRECT_FORECAST["model"], (
        f"demo ({demo_model}) и gateway ({gateway_model}) разошлись между собой — ожидался общий "
        f"пересчитанный прогноз {CORRECT_FORECAST['model']!r}"
    )
    assert demo_screen["decision"]["status"] == gateway_screen["decision"]["status"]

    # Основная фиксация дефекта #1: live обязан пересчитать прогноз (catboost_no_pak) и дать
    # то же решение, что demo/gateway дали бы с корректным прогнозом. Сейчас он расходится:
    # demo/gateway остаются на last_pak_bc и меняют режим, а live уходит на hold.
    assert demo_model == live_model, (
        f"Три пути расчёта дают РАЗНЫЙ прогноз на одном и том же срезе {AT} с condition=frozen_pak: "
        f"demo/gateway используют устаревший прогноз {demo_model!r} ({WRONG_FORECAST['value']}/"
        f"{WRONG_FORECAST['upper']}), сохранённый в срезе на момент его сборки (доверенный ПАК), "
        f"а live пересчитывает прогноз заново и получает {live_model!r} "
        f"({CORRECT_FORECAST['value']}/{CORRECT_FORECAST['upper']}), потому что учитывает "
        f"пересчитанный trust.fallback=True после отказа ПАК. bind_snapshot "
        f"(src/neftecode/infrastructure/live/snapshots.py) не пересчитывает forecast — он всегда "
        f"берёт snapshot['forecast'] как есть, независимо от инъекции отказа источника."
    )
    assert demo_screen["decision"]["status"] == live_result["decision"]["status"], (
        f"Решения разошлись вместе с прогнозом: demo/gateway status="
        f"{demo_screen['decision']['status']!r}, live status={live_result['decision']['status']!r} "
        f"(ожидался общий 'hold' по срезу {AT} с corrected forecast catboost_no_pak)."
    )
