"""Small, dependency-free HTTP building blocks shared by service processes.

The module deliberately knows nothing about a particular domain service.  Route handlers
exchange :class:`Request` objects and JSON-compatible values, while the envelope and error
mapping stay identical for every transport adapter.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date, datetime
from enum import Enum
import json
import hashlib
import math
import os
import signal
import socket
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request as URLRequest, urlopen


def clean(value: Any) -> Any:
    """Convert common Python values to strict JSON-compatible values."""
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return clean(value.value)
    if isinstance(value, Mapping):
        return {str(key): clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [clean(item) for item in value]
    if hasattr(value, "__dataclass_fields__"):
        return clean(asdict(value))
    if hasattr(value, "item"):
        return clean(value.item())
    raise TypeError(f"Значение {type(value).__name__} не поддерживается JSON")


def encode_json(value: Any) -> bytes:
    return (json.dumps(clean(value), ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n").encode()


def decode_json(payload: bytes | str) -> Any:
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    return json.loads(payload, parse_constant=lambda value: (_ for _ in ()).throw(
        ValueError(f"JSON constant {value} is not allowed")))


def content_hash(value: Any) -> str:
    """Stable SHA-256 for a JSON-compatible content value."""
    canonical = json.dumps(clean(value), ensure_ascii=False, allow_nan=False,
                           sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ServiceEnvelope:
    ok: bool
    data: Any = None
    error: dict[str, Any] | None = None
    request_id: str = "unknown"
    service: str = "unknown"
    contract_version: str = "v1"

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"contract_version": self.contract_version, "service": self.service,
                                  "request_id": self.request_id, "ok": self.ok}
        if self.ok:
            result["data"] = clean(self.data)
        else:
            result["error"] = clean(self.error or {})
        return result

    @classmethod
    def success(cls, data: Any = None, request_id: str = "unknown", service: str = "unknown") -> "ServiceEnvelope":
        return cls(True, data=data, request_id=request_id, service=service)

    @classmethod
    def failure(cls, error: "ServiceError", request_id: str = "unknown", service: str = "unknown") -> "ServiceEnvelope":
        return cls(False, error=error.to_dict(), request_id=request_id, service=service)


class ServiceError(Exception):
    def __init__(self, message: str, status: int = 400, code: str = "bad_request",
                 details: Any = None, retryable: bool = False):
        super().__init__(message)
        self.message, self.status, self.code = message, status, code
        self.details, self.retryable = details, retryable

    def to_dict(self) -> dict[str, Any]:
        result = {"code": self.code, "message": self.message, "retryable": self.retryable}
        if self.details is not None:
            result["details"] = clean(self.details)
        return result


@dataclass(frozen=True)
class Request:
    method: str
    path: str
    query: dict[str, list[str]]
    body: Any = None
    headers: Mapping[str, str] | None = None
    request_id: str | None = None


@dataclass(frozen=True)
class RawResponse:
    """Explicit escape hatch for HTML and legacy JSON responses."""
    body: bytes
    content_type: str
    status: int = 200


@dataclass(frozen=True)
class ServiceSettings:
    host: str = "127.0.0.1"
    port: int = 8765
    request_timeout_s: float = 10.0
    shutdown_timeout_s: float = 5.0
    max_workers: int = 8
    max_body_bytes: int = 1_048_576
    max_response_bytes: int = 4_194_304

    def __post_init__(self):
        if self.port <= 0 or self.port > 65535:
            raise ValueError("port должен быть в диапазоне 1..65535")
        for name in ("request_timeout_s", "shutdown_timeout_s", "max_workers", "max_body_bytes", "max_response_bytes"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} должен быть положительным")

    @classmethod
    def from_env(cls, prefix: str = "NEFTECODE_", defaults: "ServiceSettings | None" = None) -> "ServiceSettings":
        defaults = defaults or cls()
        def value(name: str, default: Any, cast: Callable[[str], Any]) -> Any:
            raw = os.getenv(prefix + name)
            if raw is None or not raw.strip():
                return default
            try:
                return cast(raw)
            except ValueError as exc:
                raise ValueError(f"{prefix}{name}: некорректное значение") from exc
        return cls(value("HOST", defaults.host, str), value("PORT", defaults.port, int),
                   value("REQUEST_TIMEOUT_S", defaults.request_timeout_s, float),
                   value("SHUTDOWN_TIMEOUT_S", defaults.shutdown_timeout_s, float),
                   value("MAX_WORKERS", defaults.max_workers, int),
                   value("MAX_BODY_BYTES", defaults.max_body_bytes, int),
                   value("MAX_RESPONSE_BYTES", defaults.max_response_bytes, int))


class ServiceHTTPClient:
    def __init__(self, timeout_s: float = 10.0, max_response_bytes: int = 4_194_304):
        if timeout_s <= 0 or max_response_bytes <= 0:
            raise ValueError("timeout_s и max_response_bytes должны быть положительными")
        self.timeout_s = timeout_s
        self.max_response_bytes = max_response_bytes

    def request(self, method: str, url: str, payload: Any = None,
                timeout_s: float | None = None, headers: Mapping[str, str] | None = None) -> ServiceEnvelope:
        body = encode_json(payload) if payload is not None else None
        request = URLRequest(url, data=body, method=method.upper(), headers={"Accept": "application/json", **(headers or {})})
        if body is not None:
            request.add_header("Content-Type", "application/json")
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
            try:
                envelope = self._decode(exc.read(self.max_response_bytes + 1), exc.code)
            except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
                raise ServiceError("Удалённый сервис вернул ошибку", 502, "upstream_error", retryable=exc.code >= 500) from exc
            if envelope.ok:
                raise ServiceError("Удалённый сервис вернул ошибочный статус", 502, "upstream_error")
            raise ServiceError(envelope.error.get("message", "Ошибка удалённого сервиса"), exc.code,
                               envelope.error.get("code", "upstream_error"), retryable=exc.code >= 500) from exc
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
                if isinstance(result, RawResponse):
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


def serve(routes: Mapping[str, Callable[[Request], Any]], settings: ServiceSettings | None = None,
          readiness: Callable[[], bool] | None = None,
          service_name: str = "service") -> ServiceHTTPServer:
    settings = settings or ServiceSettings.from_env()
    server = ServiceHTTPServer(
        (settings.host, settings.port),
        make_handler(routes, readiness, service_name=service_name, settings=settings),
    )
    previous = {name: signal.getsignal(name) for name in (signal.SIGTERM, signal.SIGINT)}
    def stop(_signum, _frame):
        # shutdown() waits for serve_forever() to leave its loop, so call it off-thread.
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
