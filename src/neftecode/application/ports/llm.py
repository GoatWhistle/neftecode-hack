from dataclasses import dataclass, field
from typing import Protocol, Sequence

ROLES = ("system", "user", "assistant", "tool")

ERROR_KINDS = ("timeout", "network", "rate_limit", "overloaded", "quota", "auth", "bad_request",
               "bad_response", "provider", "not_configured")


@dataclass(frozen=True)
class ToolSpec:

    name: str
    description: str
    parameters: dict = field(default_factory=lambda: {"type": "object", "properties": {}})

    def __post_init__(self):
        if not self.name or not self.name.replace("_", "").isalnum():
            raise ValueError(f"ToolSpec.name: недопустимое имя инструмента {self.name!r}")
        if not isinstance(self.parameters, dict) or self.parameters.get("type") != "object":
            raise ValueError(f"ToolSpec[{self.name}].parameters: ожидается JSON Schema object")


@dataclass(frozen=True)
class ToolCall:

    call_id: str
    name: str
    arguments: str = "{}"


@dataclass(frozen=True)
class LLMMessage:
    role: str
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None

    def __post_init__(self):
        if self.role not in ROLES:
            raise ValueError(f"LLMMessage.role: ожидается одно из {ROLES}")
        if self.role == "tool" and not self.tool_call_id:
            raise ValueError("LLMMessage: ответ инструмента обязан ссылаться на tool_call_id")
        if self.tool_calls and self.role != "assistant":
            raise ValueError("LLMMessage: вызовы инструментов бывают только у assistant")


@dataclass(frozen=True)
class LLMUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def to_dict(self) -> dict:
        return {"prompt_tokens": self.prompt_tokens, "completion_tokens": self.completion_tokens,
                "total_tokens": self.total_tokens}


@dataclass(frozen=True)
class LLMResponse:
    content: str
    tool_calls: tuple[ToolCall, ...] = ()
    finish_reason: str = "stop"
    usage: LLMUsage = field(default_factory=LLMUsage)
    provider: str = ""
    model: str = ""
    latency_s: float = 0.0


class LLMError(RuntimeError):

    def __init__(self, kind: str, message: str, *, retryable: bool = False, code: str | None = None):
        if kind not in ERROR_KINDS:
            kind = "provider"
        super().__init__(f"{kind}: {message}")
        self.kind = kind
        self.retryable = retryable
        self.code = code


class LLMClient(Protocol):
    provider: str
    model: str

    def chat(self, messages: Sequence[LLMMessage], tools: Sequence[ToolSpec] = (), *,
             max_tokens: int, timeout_s: float) -> LLMResponse: ...
