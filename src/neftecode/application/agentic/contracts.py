from dataclasses import dataclass
import json

from .contract_opinions import (AgentConstraint, Opinion, OPINION_FIELDS, ReasonItem, parse_constraint,
                                parse_constraints, parse_opinion)
from .contract_primitives import (CONSTRAINT_TYPES, ContractViolation, FINAL_ACTIONS, MARGIN_RANGES,
                                  MAX_CANDIDATE_VERDICTS, MAX_CONSTRAINTS, MAX_EVIDENCE, MAX_PREFERRED,
                                  MAX_REASONS, MAX_REASON_TEXT, MAX_REQUESTED_CHECKS, MAX_SUMMARY,
                                  RISK_LEVELS, ROLES, VERDICTS, _CANDIDATE, _code, _is_number, _list, _object, _text,
                                  extract_json_object)

__all__ = ["AgentConstraint", "AgentSettings", "AgentTraceEvent", "CONSTRAINT_TYPES", "ContractViolation",
           "FINAL_ACTIONS", "MARGIN_RANGES", "MAX_CANDIDATE_VERDICTS", "MAX_CONSTRAINTS", "MAX_EVIDENCE",
           "MAX_PREFERRED", "MAX_REASONS", "MAX_REASON_TEXT", "MAX_REQUESTED_CHECKS", "MAX_SUMMARY",
           "OPINION_FIELDS", "Opinion", "OrchestratorFinal", "RISK_LEVELS", "ROLES", "ReasonItem", "VERDICTS",
           "compact", "extract_json_object", "parse_constraint", "parse_constraints", "parse_final",
           "parse_opinion"]


@dataclass(frozen=True)
class OrchestratorFinal:
    action: str
    candidate_id: str | None
    reason_codes: tuple[str, ...]
    summary: str
    evidence_refs: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {"action": self.action, "candidate_id": self.candidate_id, "reason_codes": list(self.reason_codes),
                "summary": self.summary, "evidence_refs": list(self.evidence_refs)}


def parse_final(raw, *, evidence) -> OrchestratorFinal:
    data = _object(raw, "final", {"action", "candidate_id", "reason_codes", "summary", "evidence_refs"},
                   {"action", "reason_codes", "summary"})
    action = data["action"]
    if action not in FINAL_ACTIONS:
        raise ContractViolation("final.action", f"ожидается одно из {FINAL_ACTIONS}")
    candidate = data.get("candidate_id")
    if action == "select":
        if not isinstance(candidate, str) or not _CANDIDATE.match(candidate):
            raise ContractViolation("final.candidate_id", "для select нужен идентификатор кандидата")
    elif candidate is not None and not isinstance(candidate, str):
        raise ContractViolation("final.candidate_id", "ожидается строка или null")
    codes = _list(data["reason_codes"], "final.reason_codes", 5)
    if not codes:
        raise ContractViolation("final.reason_codes", "нужен хотя бы один код")
    codes = tuple(_code(c, f"final.reason_codes[{i}]") for i, c in enumerate(codes))
    summary = _text(data["summary"], "final.summary", MAX_SUMMARY)
    known = set(evidence)
    refs = tuple(dict.fromkeys(r for r in _list(data.get("evidence_refs"), "final.evidence_refs", MAX_EVIDENCE)
                               if isinstance(r, str) and r in known))
    return OrchestratorFinal(action, candidate if action == "select" else None, codes, summary, refs)


@dataclass(frozen=True)
class AgentSettings:

    max_steps: int = 5
    specialist_max_calls: int = 3
    max_specialist_consults: int = 2
    max_llm_calls: int = 12
    max_replans: int = 1
    timeout_s: float = 600.0
    max_candidates: int = 5
    max_context_chars: int = 12000
    max_tool_result_chars: int = 2500
    max_robustness_runs: int = 2
    max_tool_calls_per_response: int = 3
    max_tokens: int = 6144
    request_timeout_s: float = 120.0

    def __post_init__(self):
        for name, value in self.__dict__.items():
            if not _is_number(value) or value <= 0:
                raise ValueError(f"AgentSettings.{name}: ожидается положительное число")
        if self.max_steps < 2 or self.specialist_max_calls < 1:
            raise ValueError("AgentSettings: оркестратору нужно не меньше 2 шагов, специалисту — 1 вызов")

    @classmethod
    def from_mapping(cls, values: dict) -> "AgentSettings":
        known = {k: v for k, v in values.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def compact(value, limit: int) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    except (TypeError, ValueError):
        text = str(value)
    return text if len(text) <= limit else text[: max(0, limit - 1)] + "…"


@dataclass(frozen=True)
class AgentTraceEvent:

    seq: int
    agent: str
    step: int
    kind: str
    tool_name: str | None = None
    tool_input_summary: str | None = None
    tool_result_summary: str | None = None
    decision: str | None = None
    reason_codes: tuple[str, ...] = ()
    candidate_ids: tuple[str, ...] = ()
    latency_ms: int | None = None
    provider: str | None = None
    model: str | None = None
    usage: dict | None = None

    def to_dict(self) -> dict:
        out = {}
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if value is None or value == ():
                continue
            out[name] = list(value) if isinstance(value, tuple) else value
        return out
