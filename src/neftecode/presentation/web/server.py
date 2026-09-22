from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import errno
import os
import json
from pathlib import Path
import threading
from typing import Callable

from urllib.parse import parse_qs, urlparse

from neftecode.domain.advisory.optimizer import DEFAULT_BUDGET
from neftecode.application.ports import ScenarioRepository
from neftecode.application.conditions import SOURCE_FAULTS, canonical_conditions, changes_from, defaults_for
from neftecode.application.history.prepare import HistoryRequest, PrepareHistoricalState, run_prepared_history
from neftecode.application.history.time import HistoryError
from neftecode.presentation.demo import Demo, DemoError, snapshot_key, snapshot_title
from .cache import DecisionCache, cache_key
from .query import DemoServerError, parse_conditions
from .progress import decision_stream
from .run_meta import build_run_meta
from .static import StaticError, StaticFiles, resolve_static_dir
from .ui import error_payload

FIRST_SNAPSHOT = "20260105-080000"


@dataclass
class DemoService:

    root: Path
    demo_factory: Callable[[dict, int], Demo]
    scenario_repository: ScenarioRepository
    budget: int = DEFAULT_BUDGET
    snapshots: list = field(default_factory=list)
    default_snapshot_key: str | None = None
    decision_timeout_s: float = 660.0
    cache: DecisionCache = field(default_factory=DecisionCache)
    provenance: Callable[[], dict] = field(default=lambda: {"code": None, "model": None})
    # Источник истории P4 (каталог, обзор, подготовка момента); None — поставка без истории.
    history: object | None = None

    def snapshot_options(self) -> list[tuple[str, str]]:
        options = [(snapshot_key(item), snapshot_title(item)) for item in reversed(self.snapshots)]
        options.append(("synthetic", "синтетическое состояние сценария"))
        chosen = self.default_snapshot()
        return [o for o in options if o[0] == chosen] + [o for o in options if o[0] != chosen]

    def default_snapshot(self) -> str:
        keys = [snapshot_key(item) for item in reversed(self.snapshots)] + ["synthetic"]
        if self.default_snapshot_key is not None:
            if self.default_snapshot_key not in keys:
                raise DemoServerError(f"Срез «{self.default_snapshot_key}» не найден. Доступно: " + ", ".join(keys))
            return self.default_snapshot_key
        return FIRST_SNAPSHOT if FIRST_SNAPSHOT in keys else keys[0]

    def scenarios(self) -> list[str]:
        return self.scenario_repository.names()

    def raw(self, name: str) -> dict:
        if name not in self.scenarios():
            raise DemoServerError(f"Сценарий «{name}» не найден")
        return self.scenario_repository.raw(name)

    def canonical(self, values: dict) -> dict:
        name = (values.get("scenario") or [self.scenarios()[0]])[0]
        raw, default_snapshot = self.raw(name), self.default_snapshot()
        return canonical_conditions(parse_conditions(values), raw, name, default_snapshot)

    def decide(self, values: dict) -> dict:
        canonical = self.canonical(values)
        return self.cache.get(cache_key(canonical), lambda: self._decide(canonical))

    def recompute(self, values: dict) -> dict:
        canonical = self.canonical(values)
        payload = self._decide(canonical)
        self.cache.put(cache_key(canonical), payload)
        return payload

    def _decide(self, canonical: dict) -> dict:
        raw = self.raw(canonical["scenario"])
        snapshots = self.snapshots
        if canonical.get("at") is not None:
            result, chosen = self._decide_at(canonical, raw)
            snapshots = [*self.snapshots, chosen]
        else:
            result = self.demo_factory(raw, self.budget).run(changes_from(canonical, raw), canonical["fault"],
                                                             snapshot=canonical["snapshot"])
        payload = dict(result["screen"])
        payload["defaults"] = defaults_for(raw)
        payload["applied"] = result.get("applied", [])
        payload["injection"] = result.get("injection")
        payload["snapshot"] = result.get("snapshot")
        payload["binding"] = result.get("binding")
        payload["decision_timeout_s"] = self.decision_timeout_s
        if result.get("history") is not None:
            payload["history"] = result["history"]
        payload["run_meta"] = build_run_meta(self.provenance(), canonical, payload, snapshots, raw, snapshot_key)
        return payload

    def _decide_at(self, canonical: dict, raw: dict) -> tuple[dict, dict]:
        """Момент истории P4: подготовка одного причинного состояния и обычный pipeline решения
        тем же runner, доверием, моделью отклика и бюджетом, что у готовых срезов."""
        if self.history is None:
            raise HistoryError("history_unavailable", "Источник истории в этой поставке не подключён")
        demo = self.demo_factory(raw, self.budget)
        prepared = PrepareHistoricalState(self.history).execute(HistoryRequest(
            at=canonical["at"], fault=canonical["fault"], changes=tuple(changes_from(canonical, raw))))
        result = run_prepared_history(prepared, demo.raw, demo.runner, self.budget, demo.trust_cfg,
                                      trust_origin=demo.trust_origin, response_model=demo.response_model)
        return result, prepared["snapshot"]

    def history_catalog(self, values: dict) -> dict:
        if self.history is None:
            raise HistoryError("history_unavailable", "Источник истории в этой поставке не подключён")
        return self.history.catalog(_int(values, "offset", 0), _int(values, "limit", 50))

    def history_overview(self, values: dict) -> dict:
        if self.history is None:
            raise HistoryError("history_unavailable", "Источник истории в этой поставке не подключён")
        first = lambda key: (values.get(key) or [""])[0]
        return self.history.overview(first("start"), first("end"), _int(values, "points", 24),
                                     _int(values, "exclusion_offset", 0), _int(values, "exclusion_limit", 50))

    def loading_payload(self, name: str) -> dict:
        return {"state": "loading", "message": "Считаем решение для выбранных условий…",
                "defaults": defaults_for(self.raw(name)), "scenario": name,
                "snapshot": self.default_snapshot(), "decision_timeout_s": self.decision_timeout_s}

    def options_payload(self, name: str | None = None) -> dict:
        names = self.scenarios()
        chosen = name if name in names else (names[0] if names else None)
        try:
            payload = self.loading_payload(chosen)
        except (DemoServerError, DemoError, ValueError) as exc:
            payload = error_payload(str(exc))
            payload["defaults"] = {}
        payload["scenarios"] = names
        payload["faults"] = list(SOURCE_FAULTS)
        payload["snapshots"] = [{"key": key, "title": title} for key, title in self.snapshot_options()]
        return payload

    def warm_up(self, name: str | None = None) -> None:
        names = self.scenarios()
        chosen = name if name in names else names[0]
        try:
            self.decide({"scenario": [chosen]})
        except (DemoServerError, DemoError, ValueError):
            pass


def _int(values: dict, key: str, default: int) -> int:
    raw = (values.get(key) or [None])[0]
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise HistoryError("invalid_budget", f"{key}: ожидается целое число, получено «{raw}»") from exc


def history_error(exc: HistoryError) -> dict:
    return {"error": str(exc), "code": exc.code}


def make_handler(service: DemoService, static: StaticFiles | None = None):
    files = static if static is not None else StaticFiles(resolve_static_dir(service.root))

    class Handler(BaseHTTPRequestHandler):
        server_version = "neftecode-demo"

        def log_message(self, fmt, *args):
            pass

        def _send(self, status: int, body: bytes, content_type: str):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, payload: dict, status: int = 200):
            self._send(status, json.dumps(payload, ensure_ascii=False, default=str).encode(),
                       "application/json; charset=utf-8")

        def _stream(self, values: dict):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            stream = decision_stream(lambda: service.recompute(values))
            try:
                for frame in stream:
                    self.wfile.write(frame.encode())
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return
            finally:
                stream.close()

        def _static(self, path: str):
            try:
                asset = files.asset(path)
            except StaticError as exc:
                self._json({"error": str(exc)}, status=404)
                return
            self._send(200, asset.body, asset.content_type)

        def do_GET(self):
            parsed = urlparse(self.path)
            values = parse_qs(parsed.query)
            try:
                if parsed.path == "/api/stream":
                    self._stream(values)
                elif parsed.path == "/api/decide":
                    self._json(service.decide(values))
                elif parsed.path == "/api/defaults":
                    name = (values.get("scenario") or [service.scenarios()[0]])[0]
                    self._json(defaults_for(service.raw(name)))
                elif parsed.path == "/api/scenarios":
                    self._json({"scenarios": service.scenarios()})
                elif parsed.path == "/api/options":
                    self._json(service.options_payload((values.get("scenario") or [None])[0]))
                elif parsed.path in ("/api/history", "/api/history/overview"):
                    try:
                        self._json(service.history_catalog(values) if parsed.path == "/api/history"
                                   else service.history_overview(values))
                    except HistoryError as exc:
                        self._json(history_error(exc), status=422)
                elif parsed.path.startswith("/api/"):
                    self._json({"error": "Неизвестный путь"}, status=404)
                else:
                    self._static(parsed.path)
            except (DemoServerError, DemoError, ValueError) as exc:
                self._json({**error_payload(str(exc)), "defaults": {}}, status=200)
            except Exception as exc:
                self._json({**error_payload(f"Внутренняя ошибка: {exc}"), "defaults": {}},
                           status=500)

    return Handler


def serve(service: DemoService, port: int = 8765, static: Path | str | None = None,
          host: str | None = None):
    files = StaticFiles(resolve_static_dir(service.root, static))
    host = host or os.environ.get("NEFTECODE_HOST") or "127.0.0.1"
    try:
        httpd = ThreadingHTTPServer((host, port), make_handler(service, files))
    except OSError as exc:
        if exc.errno != errno.EADDRINUSE:
            raise
        raise DemoServerError(f"Порт {port} занят: на нём уже слушает другой процесс (по умолчанию тот же порт "
                              f"у шлюза neftecode-stack). Укажите другой: neftecode serve --port {port + 1}") from exc
    if not files.available():
        print(files.missing_message(), flush=True)
    shown = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    print(f"Демонстрация: http://{shown}:{port}/", flush=True)
    print(f"Статика фронтенда: {files.directory}", flush=True)
    print(f"Сценарии: {', '.join(service.scenarios())}; срез по умолчанию: {service.default_snapshot()}", flush=True)
    print("Первое решение считается в фоне; страница открывается сразу и покажет его, когда оно готово.", flush=True)
    print("Остановить — Ctrl+C. " + ("Сервер слушает все интерфейсы: открывать только в доверенной сети."
                                      if host in ("0.0.0.0", "::")
                                      else f"Сервер слушает только {host}."), flush=True)
    threading.Thread(target=service.warm_up, name="warm-up", daemon=True).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановлено.")
    finally:
        httpd.server_close()
    return httpd
