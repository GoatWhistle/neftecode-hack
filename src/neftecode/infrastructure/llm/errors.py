import json

from neftecode.application.ports.llm import LLMError

MAX_MESSAGE_CHARS = 200

_ZAI_CODES = {
    **{code: ("auth", False) for code in (1000, 1001, 1002, 1003, 1004)},
    **{code: ("quota", False) for code in (1113, 1308, 1309, 1310, 1311, 1313, 1315)},
    1302: ("rate_limit", True),
    1305: ("overloaded", True),
    **{code: ("bad_request", False) for code in (1210, 1211, 1212, 1213, 1214, 1261)},
    1301: ("provider", False),
    **{code: ("provider", True) for code in (1200, 1230, 1234)},
}
_NAMED_CODES = {
    "insufficient_quota": ("quota", False),
    "rate_limit_exceeded": ("rate_limit", True),
    "rate_limit_error": ("rate_limit", True),
    "overloaded_error": ("overloaded", True),
    "invalid_api_key": ("auth", False),
    "authentication_error": ("auth", False),
    "permission_error": ("auth", False),
    "invalid_request_error": ("bad_request", False),
    "request_too_large": ("bad_request", False),
    "not_found_error": ("bad_request", False),
    "api_error": ("provider", True),
}
_STATUSES = {
    400: ("bad_request", False), 401: ("auth", False), 403: ("auth", False), 404: ("bad_request", False),
    413: ("bad_request", False), 422: ("bad_request", False), 429: ("rate_limit", True),
    500: ("provider", True), 502: ("provider", True), 503: ("provider", True), 504: ("provider", True),
    529: ("overloaded", True),
}


def _short(text) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= MAX_MESSAGE_CHARS else text[:MAX_MESSAGE_CHARS - 1] + "…"


def _error_fields(body_text: str) -> tuple[str | None, str | None, str]:
    try:
        body = json.loads(body_text)
    except (TypeError, ValueError):
        return None, None, ""
    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict):
        return None, None, ""
    code = error.get("code")
    kind = error.get("type")
    return (str(code) if code not in (None, "") else None,
            str(kind) if kind else None, _short(error.get("message") or ""))


def map_http_error(status: int, body_text: str) -> LLMError:
    code, error_type, message = _error_fields(body_text)
    if code is not None and code.isdigit() and int(code) in _ZAI_CODES:
        kind, retryable = _ZAI_CODES[int(code)]
    elif code in _NAMED_CODES:
        kind, retryable = _NAMED_CODES[code]
    elif error_type in _NAMED_CODES:
        kind, retryable = _NAMED_CODES[error_type]
    else:
        kind, retryable = _STATUSES.get(status, ("provider", status >= 500))
    label = f"HTTP {status}" + (f", код {code}" if code else "")
    return LLMError(kind, f"{label}: {message}" if message else label, retryable=retryable,
                    code=code or str(status))


def map_transport_error(exc: BaseException) -> LLMError:
    reason = getattr(exc, "reason", None)
    if isinstance(exc, TimeoutError) or isinstance(reason, TimeoutError):
        return LLMError("timeout", "превышено время ожидания ответа провайдера", retryable=True)
    detail = _short(reason if reason is not None else exc) or type(exc).__name__
    return LLMError("network", f"сетевая ошибка {type(exc).__name__}: {detail}", retryable=True)
