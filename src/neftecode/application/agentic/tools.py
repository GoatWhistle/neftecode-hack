"""Deterministic tools agents may call, their argument schemas and per-agent allowlists.

A tool reads the session; it never changes a limit, a gate verdict or a figure. Arguments are validated
against the declared schema before the handler runs, and results are compact JSON with an evidence
reference an agent must cite.
"""
from collections.abc import Callable
from dataclasses import dataclass
import json
import math

from neftecode.application.ports.llm import ToolSpec
from neftecode.domain.shared.primitives import PRODUCT_LIMITS

from .contracts import CONSTRAINT_TYPES, FINAL_ACTIONS, MARGIN_RANGES, RISK_LEVELS, VERDICTS, compact, parse_constraints
from .session import DecisionSession, SessionError

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
    """A small JSON Schema subset: object, array, string, number, integer, boolean; enum, required, bounds."""
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
        if not isinstance(value, str) or len(value) > schema.get("maxLength", 10_000):
            raise ArgumentError(f"{path}: ожидается строка")
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
        except Exception as exc:  # a tool failure is reported to the agent, never promoted to a decision
            return self._error(name, arguments_text, f"tool_failed: {type(exc).__name__}")
        payload = {"evidence_ref": ref, **result}
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        if len(text) > self.max_result_chars:
            text = json.dumps({"evidence_ref": ref, "truncated": True,
                               "partial": text[: max(0, self.max_result_chars - 120)]}, ensure_ascii=False)
        ids = arguments.get("candidate_ids") or ([arguments["candidate_id"]] if "candidate_id" in arguments else [])
        return ToolOutcome(True, text, ref, compact(arguments, 200), compact(result, 300),
                           tuple(str(i) for i in ids)[:5])

    @staticmethod
    def _error(name, arguments_text, error: str) -> ToolOutcome:
        text = json.dumps({"error": error[:200]}, ensure_ascii=False)
        return ToolOutcome(False, text, None, str(arguments_text or "")[:200], text, (), error[:200])


QUALITY_TOOLS = ("get_quality_margins", "get_quality_trajectory", "get_forecast_and_uncertainty",
                 "get_tank_projection", "get_lookahead", "get_robustness", "get_response_effect",
                 "compare_candidates")
RELIABILITY_TOOLS = ("get_operating_state", "get_setpoint_changes", "get_control_margins",
                     "get_outflow_utilization", "get_inventory_projection", "check_hard_constraints",
                     "get_robustness", "get_lookahead", "compare_operating_load")
ORCHESTRATOR_TOOLS = ("inspect_candidate", "compare_candidates", "search_candidates", "rank_allowed",
                      "ask_quality_agent", "ask_reliability_agent")


def _compare(session: DecisionSession, ids) -> dict:
    rows = []
    for cid in dict.fromkeys(ids):
        try:
            rows.append(session.card(cid))
        except SessionError as exc:
            rows.append({"id": str(cid)[:80], "error": str(exc)})
    return {"candidates": rows}


def _operating_load(session: DecisionSession, ids) -> dict:
    rows = []
    for cid in dict.fromkeys(ids):
        try:
            evaluation, plan = session.candidate(cid)
        except SessionError as exc:
            rows.append({"id": str(cid)[:80], "error": str(exc)})
            continue
        rows.append({"id": cid, "kind": session.plan_kind(plan), "changes": plan.changes,
                     "severity_index": evaluation.severity_index,
                     "max_outflow_utilization": session.outflow_utilization(cid)["max_utilization"],
                     "worst_control_margin_share": session.control_margins(cid)["worst"]})
    return {"candidates": rows}


def _search(session: DecisionSession, arguments: dict) -> dict:
    accepted, rejected = parse_constraints(arguments.get("constraints", []), "constraints")
    result = session.search(accepted)
    result["constraints_rejected"] = rejected
    return result


def _rank(session: DecisionSession) -> dict:
    result = session.rank_allowed()
    return {k: v for k, v in result.items() if not k.startswith("_")}


def session_tools(session: DecisionSession) -> dict[str, Tool]:
    """Every deterministic tool bound to one session."""
    one = _schema({"candidate_id": CANDIDATE}, ["candidate_id"])
    many = _schema({"candidate_ids": CANDIDATES}, ["candidate_ids"])
    tools = [
        Tool(ToolSpec("get_quality_margins", "Запас до каждого предела продукта по траектории кандидата "
                      "(минимум по времени, источник предела).", one),
             lambda a: {"margins": session.quality_margins(a["candidate_id"])}, "candidate_id"),
        Tool(ToolSpec("get_quality_trajectory", "Значения свойства смеси по времени у кандидата.",
                      _schema({"candidate_id": CANDIDATE, "limit": {"type": "string", "enum": sorted(PRODUCT_LIMITS)}},
                              ["candidate_id", "limit"])),
             lambda a: session.quality_trajectory(a["candidate_id"], a["limit"]), "candidate_id"),
        Tool(ToolSpec("get_forecast_and_uncertainty", "Прогноз серы притока, его источник и интервал; "
                      "доверие к данным ЛИМС/ПАК и их возраст.", _schema()),
             lambda a: {"forecast": session.forecast(), "data_trust": session.data_trust()}),
        Tool(ToolSpec("get_tank_projection", "Остатки резервуаров по времени и правило конечного запаса.", one),
             lambda a: session.tank_projection(a["candidate_id"]), "candidate_id"),
        Tool(ToolSpec("get_inventory_projection", "Остатки резервуаров по времени и правило конечного запаса.", one),
             lambda a: session.tank_projection(a["candidate_id"]), "candidate_id"),
        Tool(ToolSpec("get_lookahead", "Расчёт за горизонтом: через сколько часов качество выйдет за предел.", one),
             lambda a: session.lookahead(a["candidate_id"]), "candidate_id"),
        Tool(ToolSpec("get_robustness", "Проверка плана на заданных отклонениях модели (ограниченное число запусков).",
                      one),
             lambda a: session.robustness(a["candidate_id"]), "candidate_id"),
        Tool(ToolSpec("get_response_effect", "Эффект изменения температуры входа реактора ГО: модель по данным "
                      "(если подключена) и сценарная модель.",
                      _schema({"delta_t_c": {"type": "number", "minimum": -2, "maximum": 2}}, ["delta_t_c"])),
             lambda a: session.response_effect_for(a["delta_t_c"]), "delta_t_c"),
        Tool(ToolSpec("compare_candidates", "Сравнение кандидатов: выпуск, стоимость, тяжесть, запасы качества.", many),
             lambda a: _compare(session, a["candidate_ids"]), "candidate_ids"),
        Tool(ToolSpec("get_operating_state", "Текущие уставки с диапазонами и шагом, рецепт, выпуск, резервуары, "
                      "подтверждённые действия.", _schema()),
             lambda a: session.operating_state()),
        Tool(ToolSpec("get_setpoint_changes", "Изменения кандидата относительно текущего режима по шагам.", one),
             lambda a: session.setpoint_changes(a["candidate_id"]), "candidate_id"),
        Tool(ToolSpec("get_control_margins", "Близость уставок кандидата к границам диапазона (доля диапазона).", one),
             lambda a: session.control_margins(a["candidate_id"]), "candidate_id"),
        Tool(ToolSpec("get_outflow_utilization", "Загрузка отбора из резервуаров относительно предела.", one),
             lambda a: {"candidate_id": a["candidate_id"], **session.outflow_utilization(a["candidate_id"])},
             "candidate_id"),
        Tool(ToolSpec("check_hard_constraints", "Итог обязательных проверок Gate для кандидата.", one),
             lambda a: session.hard_constraints(a["candidate_id"]), "candidate_id"),
        Tool(ToolSpec("compare_operating_load", "Сравнение эксплуатационной нагрузки кандидатов.", many),
             lambda a: _operating_load(session, a["candidate_ids"]), "candidate_ids"),
        Tool(ToolSpec("inspect_candidate", "Карточка кандидата с запасами качества, изменениями и загрузкой отбора.",
                      one),
             lambda a: {"card": session.card(a["candidate_id"]),
                        "margins": session.quality_margins(a["candidate_id"]),
                        "changes": session.setpoint_changes(a["candidate_id"])}, "candidate_id"),
        Tool(ToolSpec("search_candidates", "Новый поиск с ужесточающими ограничениями: оценивает ещё не "
                      "рассмотренные планы в пределах бюджета. Число запусков ограничено.",
                      _schema({"constraints": {"type": "array", "items": CONSTRAINT, "maxItems": 4}},
                              ["constraints"])),
             lambda a: _search(session, a), None),
        Tool(ToolSpec("rank_allowed", "Детерминированное ранжирование допустимых кандидатов после ограничений "
                      "и запретов.", _schema()),
             lambda a: _rank(session)),
    ]
    return {tool.spec.name: tool for tool in tools}


OPINION_SCHEMA = _schema({
    "verdict": {"type": "string", "enum": list(VERDICTS)},
    "risk_level": {"type": "string", "enum": list(RISK_LEVELS)},
    "reasons": {"type": "array", "maxItems": 6, "items": _schema(
        {"code": {"type": "string", "maxLength": 40}, "text": {"type": "string", "maxLength": 300},
         "candidate_id": CANDIDATE}, ["code", "text"])},
    "requested_checks": {"type": "array", "maxItems": 5, "items": {"type": "string", "maxLength": 60}},
    "proposed_constraints": {"type": "array", "maxItems": 4, "items": CONSTRAINT},
    "preferred_candidates": {"type": "array", "maxItems": 3, "items": {"type": "string", "maxLength": 80}},
    "candidate_verdicts": {"type": "object", "additionalProperties": {"type": "string", "enum": list(VERDICTS)}},
    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    "evidence_refs": {"type": "array", "maxItems": 10, "items": {"type": "string", "maxLength": 80}},
}, ["verdict", "risk_level", "reasons", "confidence", "evidence_refs"])

SUBMIT_OPINION = ToolSpec("submit_opinion", "Финальное мнение агента в строгой схеме. Вызывается один раз.",
                          OPINION_SCHEMA)

FINALIZE = ToolSpec("finalize", "Финальное действие оркестратора: select, keep_legacy или refuse.", _schema({
    "action": {"type": "string", "enum": list(FINAL_ACTIONS)},
    "candidate_id": {"type": "string", "maxLength": 80},
    "reason_codes": {"type": "array", "maxItems": 5, "items": {"type": "string", "maxLength": 40}},
    "summary": {"type": "string", "maxLength": 400},
    "evidence_refs": {"type": "array", "maxItems": 10, "items": {"type": "string", "maxLength": 80}},
}, ["action", "reason_codes", "summary"]))
