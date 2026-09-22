from __future__ import annotations

from dataclasses import replace
import json
import signal
import socket
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Iterator, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request as URLRequest, urlopen

from .envelope import (RawResponse, Request, ServiceEnvelope, ServiceError, ServiceSettings, StreamResponse, decode_json,
                       encode_json)


class ServiceHTTPClient:
    def __init__(self, timeout_s: float = 10.0, max_response_bytes: int = 4_194_304):
        if timeout_s <= 0 or max_response_bytes <= 0:
            raise ValueError("timeout_s и max_response_bytes должны быть положительными")
        self.timeout_s = timeout_s
        self.max_response_bytes = max_response_bytes

    @staticmethod
    def _prepare(method: str, url: str, payload: Any, accept: str, headers: Mapping[str, str] | None) -> URLRequest:
        body = encode_json(payload) if payload is not None else None
        request = URLRequest(url, data=body, method=method.upper(), headers={"Accept": accept, **(headers or {})})
        if body is not None:
            request.add_header("Content-Type", "application/json")
        return request

    def _http_error(self, exc: HTTPError) -> ServiceError:
        try:
            envelope = self._decode(exc.read(self.max_response_bytes + 1), exc.code)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            return ServiceError("Удалённый сервис вернул ошибку", 502, "upstream_error", retryable=exc.code >= 500)
        if envelope.ok:
            return ServiceError("Удалённый сервис вернул ошибочный статус", 502, "upstream_error")
        return ServiceError(envelope.error.get("message", "Ошибка удалённого сервиса"), exc.code,
                            envelope.error.get("code", "upstream_error"), retryable=exc.code >= 500)

    def stream(self, method: str, url: str, payload: Any = None, timeout_s: float | None = None,
               headers: Mapping[str, str] | None = None) -> Iterator[tuple[str, Any]]:
        """События SSE удалённого сервиса по мере прихода: (event, data).

        timeout_s — общий срок всего потока, а не одного чтения: удалённый сервис шлёт tick раз в секунду,
        поэтому зависший расчёт обнаруживается по сроку, а не ждёт бесконечно. Кадр больше
        max_response_bytes — ошибка, а не молча обрезанный результат.
        """
        limit = timeout_s if timeout_s is not None else self.timeout_s
        deadline = time.monotonic() + limit
        request = self._prepare(method, url, payload, "text/event-stream", headers)
        try:
            response = urlopen(request, timeout=limit)
        except HTTPError as exc:
            raise self._http_error(exc) from exc
        except (TimeoutError, socket.timeout) as exc:
            raise ServiceError("Таймаут удалённого сервиса", 504, "upstream_timeout", retryable=True) from exc
        except URLError as exc:
            reason = getattr(exc, "reason", None)
            if isinstance(reason, (TimeoutError, socket.timeout)):
                raise ServiceError("Таймаут удалённого сервиса", 504, "upstream_timeout", retryable=True) from exc
            raise ServiceError("Удалённый сервис недоступен", 503, "upstream_unavailable", retryable=True) from exc
        with response:
            event, data, size = "message", [], 0
            while True:
                if time.monotonic() > deadline:
                    raise ServiceError("Таймаут удалённого сервиса", 504, "upstream_timeout", retryable=True)
                try:
                    raw = response.readline(self.max_response_bytes + 1)
                except (TimeoutError, socket.timeout) as exc:
                    raise ServiceError("Таймаут удалённого сервиса", 504, "upstream_timeout", retryable=True) from exc
                if not raw:
                    return
                size += len(raw)
                if size > self.max_response_bytes:
                    raise ServiceError("Кадр удалённого сервиса слишком большой", 502, "upstream_response_too_large")
                line = raw.decode("utf-8").rstrip("\r\n")
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    data.append(line[5:].strip())
                elif not line and data:
                    try:
                        value = json.loads("\n".join(data))
                    except json.JSONDecodeError as exc:
                        raise ServiceError("Некорректный кадр удалённого сервиса", 502, "invalid_upstream") from exc
                    yield event, value
                    event, data, size = "message", [], 0

    def request(self, method: str, url: str, payload: Any = None,
                timeout_s: float | None = None, headers: Mapping[str, str] | None = None) -> ServiceEnvelope:
        request = self._prepare(method, url, payload, "application/json", headers)
        try:
            with urlopen(request, timeout=timeout_s if timeout_s is not None else self.timeout_s) as response:
                declared = response.headers.get("Content-Length")
                if declared is not None and (not declared.isdigit() or int(declared) > self.max_response_bytes):
                    raise ServiceError("Ответ удалённого сервиса слишком большой", 502, "upstream_response_too_large")
                chunks, total = [], 0
                while True:
                    chunk = response.read(min(65536, self.max_response_bytes - total + 1))
                    if not chunk:
                        break
                    chunks.append(chunk); total += len(chunk)
                    if total > self.max_response_bytes:
                        raise ServiceError("Ответ удалённого сервиса слишком большой", 502, "upstream_response_too_large")
                return self._decode(b"".join(chunks), response.status)
        except HTTPError as exc:
            raise self._http_error(exc) from exc
        except (TimeoutError, socket.timeout) as exc:
            raise ServiceError("Таймаут удалённого сервиса", 504, "upstream_timeout", retryable=True) from exc
        except URLError as exc:
            reason = getattr(exc, "reason", None)
            if isinstance(reason, (TimeoutError, socket.timeout)):
                raise ServiceError("Таймаут удалённого сервиса", 504, "upstream_timeout", retryable=True) from exc
            raise ServiceError("Удалённый сервис недоступен", 503, "upstream_unavailable", retryable=True) from exc

    @staticmethod
    def _decode(body: bytes, status: int) -> ServiceEnvelope:
        value = decode_json(body)
        if not isinstance(value, dict) or value.get("contract_version") != "v1" or not isinstance(value.get("ok"), bool):
            raise ServiceError("Некорректный ответ удалённого сервиса", 502, "invalid_upstream")
        if not isinstance(value.get("service"), str) or not value["service"] or not isinstance(value.get("request_id"), str) or not value["request_id"]:
            raise ServiceError("Некорректный ответ удалённого сервиса", 502, "invalid_upstream")
        if value["ok"] is False and not isinstance(value.get("error"), dict):
            raise ServiceError("Некорректная ошибка удалённого сервиса", 502, "invalid_upstream")
        return ServiceEnvelope(value["ok"], value.get("data"), value.get("error"), value["request_id"], value["service"], value["contract_version"])


def make_handler(routes: Mapping[str, Callable[[Request], Any]], readiness: Callable[[], bool] | None = None,
                 service_name: str = "service", settings: ServiceSettings | None = None):
    settings = settings or ServiceSettings()
    class Handler(BaseHTTPRequestHandler):
        server_version = "neftecode-service"
        def log_message(self, *_args):
            pass
        def _reply(self, envelope: ServiceEnvelope | RawResponse, status: int = 200, response_limit: int | None = None, request_id: str = "unknown"):
            if isinstance(envelope, StreamResponse):
                self.send_response(envelope.status)
                self.send_header("Content-Type", envelope.content_type)
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Accel-Buffering", "no")
                self.send_header("X-Request-ID", request_id)
                self.send_header("Connection", "close")
                self.end_headers()
                total = 0
                try:
                    for chunk in envelope.chunks:
                        total += len(chunk)
                        if response_limit is not None and total > response_limit:
                            break
                        self.wfile.write(chunk)
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                finally:
                    close = getattr(envelope.chunks, "close", None)
                    if close is not None:
                        close()
                return
            if isinstance(envelope, RawResponse):
                body, content_type, status = envelope.body, envelope.content_type, envelope.status
            else:
                body, content_type = encode_json(envelope.to_dict()), "application/json; charset=utf-8"
            if response_limit is not None and len(body) > response_limit:
                envelope_id = envelope.request_id if isinstance(envelope, ServiceEnvelope) else request_id
                body = encode_json(ServiceEnvelope.failure(ServiceError("Ответ слишком большой", 500, "response_too_large"), envelope_id, service_name).to_dict())
                content_type = "application/json; charset=utf-8"
                status = 500
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Request-ID", request_id if request_id != "unknown" else getattr(envelope, "request_id", "unknown"))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
        def do_GET(self):  # noqa: N802
            self._dispatch()
        def do_POST(self):  # noqa: N802
            self._dispatch()
        def _dispatch(self):
            parts = urlsplit(self.path)
            request_id = (self.headers.get("X-Request-ID") or "").strip() or str(uuid.uuid4())
            if parts.path == "/healthz":
                return self._reply(ServiceEnvelope.success({"status": "ok"}, request_id, service_name))
            if parts.path == "/readyz":
                try:
                    ready = readiness is None or bool(readiness())
                except Exception:
                    error = ServiceError("Сервис не готов", 503, "readiness_unavailable", retryable=True)
                    return self._reply(ServiceEnvelope.failure(error, request_id, service_name), 503)
                if not ready:
                    error = ServiceError("Сервис не готов", 503, "not_ready", retryable=True)
                    return self._reply(ServiceEnvelope.failure(error, request_id, service_name), 503)
                return self._reply(ServiceEnvelope.success({"status": "ready"}, request_id, service_name))
            try:
                route = routes.get(parts.path)
                if route is None:
                    raise ServiceError("Неизвестный путь", 404, "not_found")
                raw = b""
                if self.command == "POST":
                    if self.headers.get("Transfer-Encoding"):
                        raise ServiceError("Transfer-Encoding не поддерживается", 400,
                                           "unsupported_transfer_encoding")
                    value = self.headers.get("Content-Length")
                    if value is None:
                        raise ServiceError("Нужен Content-Length", 411, "length_required")
                    try:
                        length = int(value)
                    except ValueError:
                        raise ServiceError("Некорректный Content-Length", 400, "invalid_content_length")
                    if length < 0:
                        raise ServiceError("Некорректный Content-Length", 400, "invalid_content_length")
                    if length > settings.max_body_bytes:
                        raise ServiceError("Тело запроса слишком большое", 413, "request_too_large")
                    if length and not self.headers.get("Content-Type", "").lower().split(";", 1)[0].strip() == "application/json":
                        raise ServiceError("Для JSON нужен Content-Type application/json", 415, "unsupported_media_type")
                    raw = self.rfile.read(length)
                request = Request(self.command, parts.path, parse_qs(parts.query), decode_json(raw) if raw else None, dict(self.headers), request_id)
                result = route(request)
                if isinstance(result, (RawResponse, StreamResponse)):
                    return self._reply(result, request_id=request_id, response_limit=settings.max_response_bytes)
                envelope = result if isinstance(result, ServiceEnvelope) else ServiceEnvelope.success(result, request_id, service_name)
                if envelope.service == "unknown" or envelope.request_id == "unknown":
                    envelope = replace(envelope, service=service_name,
                                       request_id=request_id if envelope.request_id == "unknown" else envelope.request_id)
                self._reply(envelope, response_limit=settings.max_response_bytes, request_id=request_id)
            except ServiceError as exc:
                self._reply(ServiceEnvelope.failure(exc, request_id, service_name), exc.status)
            except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
                self._reply(ServiceEnvelope.failure(ServiceError(str(exc), 400, "invalid_json"), request_id, service_name), 400)
            except Exception as exc:  # pragma: no cover
                self._reply(ServiceEnvelope.failure(ServiceError(str(exc), 500, "internal_error"), request_id, service_name), 500)
    return Handler


class ServiceHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def use_utf8_streams() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None and getattr(stream, "encoding", "").lower() not in ("utf-8", "utf8"):
            reconfigure(encoding="utf-8", errors="replace")


def serve(routes: Mapping[str, Callable[[Request], Any]], settings: ServiceSettings | None = None,
          readiness: Callable[[], bool] | None = None,
          service_name: str = "service") -> ServiceHTTPServer:
    use_utf8_streams()
    settings = settings or ServiceSettings.from_env()
    server = ServiceHTTPServer(
        (settings.host, settings.port),
        make_handler(routes, readiness, service_name=service_name, settings=settings),
    )
    previous = {name: signal.getsignal(name) for name in (signal.SIGTERM, signal.SIGINT)}
    def stop(_signum, _frame):
        threading.Thread(target=server.shutdown, name="service-shutdown", daemon=True).start()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        server.serve_forever()
    finally:
        for name, handler in previous.items():
            signal.signal(name, handler)
        server.server_close()
    return server
