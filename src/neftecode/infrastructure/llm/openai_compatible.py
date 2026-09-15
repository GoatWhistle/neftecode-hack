"""OpenAI-compatible chat completions adapter (Z.AI Coding Plan, OpenAI, local endpoints).

HTTP goes through `urllib.request.urlopen`, looked up at call time so tests can replace it.
Provider reasoning (`reasoning_content`) is discarded and never reaches `LLMResponse`.
"""
import http.client
import json
import time
import urllib.error
import urllib.request
from typing import Callable, Sequence

from neftecode.application.ports.llm import LLMError, LLMMessage, LLMResponse, LLMUsage, ToolCall, ToolSpec

from .config import Secret
from .errors import map_http_error, map_transport_error


def post_json(url: str, headers: dict, body: dict, timeout_s: float, secret: Secret) -> dict:
    """POST a JSON body and return the decoded JSON object, mapping every failure to `LLMError`."""
    request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers,
                                     method="POST")
    try:
        try:
            with urllib.request.urlopen(request, timeout=timeout_s) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            try:
                text = exc.read().decode("utf-8", "replace")
            except Exception:
                text = ""
            raise map_http_error(exc.code, text) from None
        except (OSError, http.client.HTTPException) as exc:
            raise map_transport_error(exc) from None
        try:
            data = json.loads(raw)
        except ValueError:
            raise LLMError("bad_response", "ответ провайдера не является JSON") from None
        if not isinstance(data, dict):
            raise LLMError("bad_response", "ответ провайдера не является JSON-объектом")
        return data
    except LLMError as error:
        raise _redacted(error, secret) from None


def _redacted(error: LLMError, secret: Secret) -> LLMError:
    value = secret.reveal()
    if not value or value not in str(error):
        return error
    message = str(error).split(": ", 1)[-1].replace(value, "***")
    return LLMError(error.kind, message, retryable=error.retryable, code=error.code)


def call_with_retries(attempt: Callable[[], LLMResponse], max_retries: int,
                      sleep: Callable[[float], None]) -> LLMResponse:
    """Retry only retryable errors, at most `max_retries` extra times, with 1s, 2s, ... backoff."""
    retry = 0
    while True:
        try:
            return attempt()
        except LLMError as error:
            if not error.retryable or retry >= max_retries:
                raise
            sleep(float(2 ** retry))
            retry += 1


def check_finish(finish_reason: str, content: str, tool_calls: tuple) -> None:
    """Reject responses that carry no usable answer."""
    if finish_reason == "sensitive":
        raise LLMError("provider", "провайдер заблокировал ответ (sensitive)", code="sensitive")
    if finish_reason == "network_error":
        raise LLMError("provider", "провайдер прервал генерацию (network_error)", retryable=True,
                       code="network_error")
    if finish_reason == "model_context_window_exceeded":
        raise LLMError("bad_request", "превышено окно контекста модели", code=finish_reason)
    if finish_reason == "length" and not tool_calls and not content.strip():
        raise LLMError("bad_response", "ответ обрезан по max_tokens и не содержит результата",
                       code="length")


def token_count(value) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


class OpenAICompatibleClient:
    def __init__(self, provider: str, base_url: str, model: str, api_key: Secret, temperature: float = 0.2,
                 max_retries: int = 1, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic):
        self.provider = provider
        self.base_url = base_url
        self.model = model
        self._api_key = api_key
        self.temperature = temperature
        self.max_retries = max_retries
        self._sleep = sleep
        self._clock = clock

    def __repr__(self) -> str:
        return f"OpenAICompatibleClient(provider={self.provider!r}, model={self.model!r})"

    def describe(self) -> dict:
        return {"provider": self.provider, "model": self.model, "base_url": self.base_url}

    def chat(self, messages: Sequence[LLMMessage], tools: Sequence[ToolSpec] = (), *,
             max_tokens: int, timeout_s: float) -> LLMResponse:
        body = {"model": self.model, "messages": [_message(item) for item in messages],
                "max_tokens": max_tokens, "temperature": self.temperature, "stream": False}
        if tools:
            body["tools"] = [{"type": "function", "function": {
                "name": tool.name, "description": tool.description, "parameters": tool.parameters}}
                for tool in tools]
            body["tool_choice"] = "auto"
        headers = {"Authorization": f"Bearer {self._api_key.reveal()}",
                   "Content-Type": "application/json", "Accept": "application/json"}
        url = f"{self.base_url.rstrip('/')}/chat/completions"
        started = self._clock()
        data = call_with_retries(lambda: self._once(url, headers, body, timeout_s), self.max_retries,
                                 self._sleep)
        return LLMResponse(**data, provider=self.provider, model=self.model,
                           latency_s=max(0.0, self._clock() - started))

    def _once(self, url, headers, body, timeout_s) -> dict:
        return _parse(post_json(url, headers, body, timeout_s, self._api_key))


def _message(message: LLMMessage) -> dict:
    if message.role == "tool":
        return {"role": "tool", "content": message.content, "tool_call_id": message.tool_call_id}
    mapped = {"role": message.role, "content": message.content}
    if message.tool_calls:
        mapped["tool_calls"] = [{"id": call.call_id, "type": "function",
                                 "function": {"name": call.name, "arguments": call.arguments}}
                                for call in message.tool_calls]
    return mapped


def _parse(data: dict) -> dict:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise LLMError("bad_response", "в ответе провайдера нет choices")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise LLMError("bad_response", "в ответе провайдера нет message")
    content = message.get("content") or ""
    if not isinstance(content, str):
        raise LLMError("bad_response", "content ответа не является строкой")
    calls = []
    for index, raw in enumerate(message.get("tool_calls") or ()):
        function = raw.get("function") if isinstance(raw, dict) else None
        if not isinstance(function, dict) or not isinstance(function.get("name"), str):
            raise LLMError("bad_response", "tool_calls ответа без имени функции")
        arguments = function.get("arguments")
        if isinstance(arguments, dict):
            arguments = json.dumps(arguments, ensure_ascii=False)
        calls.append(ToolCall(str(raw.get("id") or f"call_{index}"), function["name"],
                              arguments if isinstance(arguments, str) and arguments else "{}"))
    tool_calls = tuple(calls)
    finish_reason = choices[0].get("finish_reason") or ("tool_calls" if tool_calls else "stop")
    check_finish(finish_reason, content, tool_calls)
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    prompt, completion = token_count(usage.get("prompt_tokens")), token_count(usage.get("completion_tokens"))
    total = token_count(usage.get("total_tokens")) or prompt + completion
    return {"content": content, "tool_calls": tool_calls, "finish_reason": str(finish_reason),
            "usage": LLMUsage(prompt, completion, total)}
