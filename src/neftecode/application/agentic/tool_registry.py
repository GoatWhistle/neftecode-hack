from collections.abc import Callable
from dataclasses import dataclass
import json
import math

from neftecode.application.ports.llm import ToolSpec

from .contracts import CONSTRAINT_TYPES, MARGIN_RANGES, compact
from .session import SessionError


CANDIDATE = {"type": "string", "maxLength": 80, "description": "Идентификатор кандидата из shortlist"}
CANDIDATES = {"type": "array", "items": {"type": "string", "maxLength": 80}, "maxItems": 5}
CONSTRAINT = {"type": "object", "additionalProperties": False, "required": ["type"],
              "properties": {"type": {"type": "string", "enum": sorted(CONSTRAINT_TYPES)},
                             "limit": {"type": "string", "enum": sorted(MARGIN_RANGES)},
                             "value": {"type": "number"}}}


def _schema(properties: dict | None = None, required=()) -> dict:
    return {"type": "object", "additionalProperties": False, "properties": properties or {},
            "required": list(required)}


class ArgumentError(ValueError):
    pass


def validate_arguments(schema: dict, value, path: str = "arguments") -> None:
    kind = schema.get("type")
    if kind == "object":
        if not isinstance(value, dict):
            raise ArgumentError(f"{path}: ожидается объект")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extra = sorted(set(value) - set(properties))
            if extra:
                raise ArgumentError(f"{path}: неизвестные поля {extra}")
        for name in schema.get("required", ()):
            if name not in value:
                raise ArgumentError(f"{path}: нет поля {name}")
        for name, item in value.items():
            if name in properties:
                validate_arguments(properties[name], item, f"{path}.{name}")
    elif kind == "array":
        if not isinstance(value, list):
            raise ArgumentError(f"{path}: ожидается список")
        if len(value) > schema.get("maxItems", len(value)):
            raise ArgumentError(f"{path}: не больше {schema['maxItems']} элементов")
        for index, item in enumerate(value):
            validate_arguments(schema.get("items", {}), item, f"{path}[{index}]")
    elif kind == "string":
        if not isinstance(value, str):
            raise ArgumentError(f"{path}: ожидается строка")
        limit = schema.get("maxLength", 10_000)
        if len(value) > limit:
            raise ArgumentError(f"{path}: строка длиннее {limit} символов, сократите до {limit}")
    elif kind in ("number", "integer"):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ArgumentError(f"{path}: ожидается число")
        if kind == "integer" and int(value) != value:
            raise ArgumentError(f"{path}: ожидается целое")
        if "minimum" in schema and value < schema["minimum"] or "maximum" in schema and value > schema["maximum"]:
            raise ArgumentError(f"{path}: вне диапазона")
    elif kind == "boolean":
        if not isinstance(value, bool):
            raise ArgumentError(f"{path}: ожидается true/false")
    if "enum" in schema and value not in schema["enum"]:
        raise ArgumentError(f"{path}: ожидается одно из {schema['enum']}")


@dataclass(frozen=True)
class Tool:
    spec: ToolSpec
    handler: Callable[[dict], dict]
    evidence_argument: str | None = None


@dataclass(frozen=True)
class ToolOutcome:
    ok: bool
    text: str
    evidence_ref: str | None
    input_summary: str
    result_summary: str
    result_full: str
    candidate_ids: tuple[str, ...] = ()
    error: str | None = None


def evidence_ref(name: str, arguments: dict, argument: str | None) -> str:
    value = arguments.get(argument) if argument else ""
    if isinstance(value, list):
        value = ",".join(str(v) for v in value)
    return f"{name}:{value if value is not None else ''}"[:80]


class ToolRegistry:
    def __init__(self, tools: dict[str, Tool], max_result_chars: int):
        self.tools = dict(tools)
        self.max_result_chars = max_result_chars

    def add(self, tool: Tool) -> None:
        self.tools[tool.spec.name] = tool

    def specs(self, names) -> list[ToolSpec]:
        return [self.tools[name].spec for name in names if name in self.tools]

    def execute(self, name: str, arguments_text: str, allowlist) -> ToolOutcome:
        if name not in allowlist or name not in self.tools:
            return self._error(name, arguments_text, "tool_not_allowed")
        tool = self.tools[name]
        try:
            arguments = json.loads(arguments_text or "{}")
        except (TypeError, ValueError):
            return self._error(name, arguments_text, "arguments_not_json")
        try:
            validate_arguments(tool.spec.parameters, arguments)
        except ArgumentError as exc:
            return self._error(name, arguments_text, f"invalid_arguments: {exc}")
        ref = evidence_ref(name, arguments, tool.evidence_argument)
        try:
            result = tool.handler(arguments)
        except SessionError as exc:
            return self._error(name, arguments_text, str(exc))
        except Exception as exc:
            return self._error(name, arguments_text, f"tool_failed: {type(exc).__name__}")
        payload = {"evidence_ref": ref, **result}
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        if len(text) > self.max_result_chars:
            text = json.dumps({"evidence_ref": ref, "truncated": True,
                               "partial": text[: max(0, self.max_result_chars - 120)]}, ensure_ascii=False)
        ids = arguments.get("candidate_ids") or ([arguments["candidate_id"]] if "candidate_id" in arguments else [])
        return ToolOutcome(True, text, ref, compact(arguments, 200), compact(result, 300), text,
                           tuple(str(i) for i in ids)[:5])

    @staticmethod
    def _error(name, arguments_text, error: str) -> ToolOutcome:
        text = json.dumps({"error": error[:200]}, ensure_ascii=False)
        return ToolOutcome(False, text, None, str(arguments_text or "")[:200], text, text, (), error[:200])
