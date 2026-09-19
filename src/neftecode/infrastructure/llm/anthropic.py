import json
import time
from typing import Callable, Sequence

from neftecode.application.ports.llm import LLMError, LLMMessage, LLMResponse, LLMUsage, ToolCall, ToolSpec

from .config import Secret
from .openai_compatible import call_with_retries, check_finish, post_json, token_count

ANTHROPIC_VERSION = "2023-06-01"
STOP_REASONS = {"tool_use": "tool_calls", "end_turn": "stop", "stop_sequence": "stop", "max_tokens": "length",
                "refusal": "sensitive"}


class AnthropicClient:
    provider = "anthropic"

    def __init__(self, base_url: str, model: str, api_key: Secret, temperature: float = 0.2,
                 max_retries: int = 1, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic):
        self.base_url = base_url
        self.model = model
        self._api_key = api_key
        self.temperature = temperature
        self.max_retries = max_retries
        self._sleep = sleep
        self._clock = clock

    def __repr__(self) -> str:
        return f"AnthropicClient(model={self.model!r})"

    def describe(self) -> dict:
        return {"provider": self.provider, "model": self.model, "base_url": self.base_url}

    def chat(self, messages: Sequence[LLMMessage], tools: Sequence[ToolSpec] = (), *,
             max_tokens: int, timeout_s: float) -> LLMResponse:
        system, mapped = _messages(messages)
        body = {"model": self.model, "messages": mapped, "max_tokens": max_tokens,
                "temperature": self.temperature}
        if system:
            body["system"] = system
        if tools:
            body["tools"] = [{"name": tool.name, "description": tool.description,
                              "input_schema": tool.parameters} for tool in tools]
            body["tool_choice"] = {"type": "auto"}
        headers = {"x-api-key": self._api_key.reveal(), "anthropic-version": ANTHROPIC_VERSION,
                   "content-type": "application/json"}
        url = f"{self.base_url.rstrip('/')}/v1/messages"
        started = self._clock()
        data = call_with_retries(lambda t: _parse(post_json(url, headers, body, t, self._api_key)),
                                 self.max_retries, self._sleep, timeout_s, self._clock, started)
        return LLMResponse(**data, provider=self.provider, model=self.model,
                           latency_s=max(0.0, self._clock() - started))


def _arguments(text: str) -> dict:
    try:
        value = json.loads(text or "{}")
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _messages(messages: Sequence[LLMMessage]) -> tuple[str, list[dict]]:
    system, mapped = [], []
    for message in messages:
        if message.role == "system":
            system.append(message.content)
        elif message.role == "tool":
            block = {"type": "tool_result", "tool_use_id": message.tool_call_id, "content": message.content}
            if mapped and mapped[-1].get("_tool_results"):
                mapped[-1]["content"].append(block)
            else:
                mapped.append({"role": "user", "content": [block], "_tool_results": True})
        elif message.role == "assistant" and message.tool_calls:
            blocks = [{"type": "text", "text": message.content}] if message.content else []
            blocks += [{"type": "tool_use", "id": call.call_id, "name": call.name,
                        "input": _arguments(call.arguments)} for call in message.tool_calls]
            mapped.append({"role": "assistant", "content": blocks})
        else:
            mapped.append({"role": message.role, "content": message.content})
    for item in mapped:
        item.pop("_tool_results", None)
    return "\n\n".join(part for part in system if part), mapped


def _parse(data: dict) -> dict:
    blocks = data.get("content")
    if not isinstance(blocks, list):
        raise LLMError("bad_response", "в ответе провайдера нет content")
    texts, calls = [], []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            texts.append(str(block.get("text") or ""))
        elif block.get("type") == "tool_use":
            if not isinstance(block.get("name"), str):
                raise LLMError("bad_response", "tool_use ответа без имени")
            arguments = block.get("input") if isinstance(block.get("input"), dict) else {}
            calls.append(ToolCall(str(block.get("id") or f"call_{len(calls)}"), block["name"],
                                  json.dumps(arguments, ensure_ascii=False)))
    content, tool_calls = "".join(texts), tuple(calls)
    stop = data.get("stop_reason")
    finish_reason = STOP_REASONS.get(stop, stop) or ("tool_calls" if tool_calls else "stop")
    check_finish(str(finish_reason), content, tool_calls)
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    prompt, completion = token_count(usage.get("input_tokens")), token_count(usage.get("output_tokens"))
    return {"content": content, "tool_calls": tool_calls, "finish_reason": str(finish_reason),
            "usage": LLMUsage(prompt, completion, prompt + completion)}
