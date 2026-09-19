from collections.abc import Callable, Sequence
import json
import re

from neftecode.application.ports.llm import LLMMessage, LLMResponse, LLMUsage, ToolCall, ToolSpec

DETERMINISTIC_PROVIDERS = ("scripted",)

DETERMINISTIC_LABEL = "детерминированная политика, не языковая модель"

_ROLE = re.compile(r"ROLE:\s*([a-z_]+)")


def role_of(messages: Sequence[LLMMessage]) -> str:
    for message in messages:
        if message.role == "system":
            match = _ROLE.search(message.content)
            if match:
                return match.group(1)
    return "unknown"


def tool_results(messages: Sequence[LLMMessage]) -> list[dict]:
    calls = {}
    out = []
    for message in messages:
        for call in message.tool_calls:
            calls[call.call_id] = call
        if message.role == "tool":
            call = calls.get(message.tool_call_id)
            try:
                result = json.loads(message.content)
            except (TypeError, ValueError):
                result = message.content
            try:
                arguments = json.loads(call.arguments) if call else {}
            except ValueError:
                arguments = {}
            out.append({"name": call.name if call else None, "arguments": arguments, "result": result})
    return out


def context_of(messages: Sequence[LLMMessage]) -> dict:
    for message in messages:
        if message.role == "user":
            start = message.content.find("{")
            if start >= 0:
                try:
                    return json.loads(message.content[start:])
                except ValueError:
                    return {}
    return {}


def call(name: str, **arguments) -> tuple[str, dict]:
    return (name, arguments)


def respond(*calls: tuple[str, dict], content: str = "", usage: tuple[int, int] = (0, 0)) -> LLMResponse:
    tool_calls = tuple(ToolCall("", name, json.dumps(arguments, ensure_ascii=False)) for name, arguments in calls)
    return LLMResponse(content, tool_calls, "tool_calls" if tool_calls else "stop",
                       LLMUsage(usage[0], usage[1], usage[0] + usage[1]))


class _Deterministic:
    provider = "scripted"

    def __init__(self, model: str):
        self.model = model
        self.calls: list[dict] = []
        self._ids = 0

    def _finish(self, messages, tools, response: LLMResponse) -> LLMResponse:
        numbered = []
        for tool_call in response.tool_calls:
            self._ids += 1
            numbered.append(ToolCall(tool_call.call_id or f"call_{self._ids}", tool_call.name, tool_call.arguments))
        self.calls.append({"role": role_of(messages), "tools": [t.name for t in tools],
                           "requested": [c.name for c in numbered]})
        return LLMResponse(response.content, tuple(numbered), response.finish_reason, response.usage,
                           self.provider, self.model, 0.0)


class ScriptedLLM(_Deterministic):

    def __init__(self, responses: Sequence, model: str = "scripted-queue"):
        super().__init__(model)
        self._queue = list(responses)

    @property
    def remaining(self) -> int:
        return len(self._queue)

    def chat(self, messages: Sequence[LLMMessage], tools: Sequence[ToolSpec] = (), *,
             max_tokens: int, timeout_s: float) -> LLMResponse:
        if not self._queue:
            raise AssertionError("ScriptedLLM: unexpected extra model call")
        item = self._queue.pop(0)
        if isinstance(item, BaseException):
            self.calls.append({"role": role_of(messages), "tools": [t.name for t in tools], "raised": type(item).__name__})
            raise item
        if callable(item):
            item = item(messages, tools)
        return self._finish(messages, tools, item)


class PolicyLLM(_Deterministic):

    def __init__(self, policy: Callable[[str, Sequence[LLMMessage], Sequence[ToolSpec]], LLMResponse],
                 model: str = "scripted-policy"):
        super().__init__(model)
        self._policy = policy

    def chat(self, messages: Sequence[LLMMessage], tools: Sequence[ToolSpec] = (), *,
             max_tokens: int, timeout_s: float) -> LLMResponse:
        return self._finish(messages, tools, self._policy(role_of(messages), messages, tools))
