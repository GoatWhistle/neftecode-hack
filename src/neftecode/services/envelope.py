from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from enum import Enum
import json
import hashlib
import math
import os
from typing import Any, Callable, Mapping


def clean(value: Any) -> Any:
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
