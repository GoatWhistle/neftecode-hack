"""Structured contracts between language model agents and the deterministic core.

A model answer becomes a machine decision only through a parser here. Parsers are strict: unknown keys,
wrong types, values out of range and silently "almost JSON" are rejected. What a model may propose is a
closed vocabulary of constraints that can only narrow the set of plans the gate has already accepted.
"""
from dataclasses import dataclass, field
import json
import math
import re

VERDICTS = ("ACCEPT", "REVISE", "REJECT", "UNKNOWN")
RISK_LEVELS = ("low", "medium", "high", "unknown")
FINAL_ACTIONS = ("select", "keep_legacy", "refuse")
ROLES = ("orchestrator", "quality", "reliability")

_CODE = re.compile(r"^[a-z0-9_]{1,40}$")
_CANDIDATE = re.compile(r"^[A-Za-z0-9_:,.\-]{1,80}$")

MAX_REASONS = 6
MAX_REASON_TEXT = 300
MAX_CONSTRAINTS = 4
MAX_PREFERRED = 3
MAX_CANDIDATE_VERDICTS = 5
MAX_EVIDENCE = 10
MAX_REQUESTED_CHECKS = 5
MAX_SUMMARY = 400

#: Product limit id -> allowed range of an extra margin an agent may demand (units of the limit).
MARGIN_RANGES = {
    "sulfur_mgkg": (0.0, 5.0),
    "t95_c": (0.0, 20.0),
    "cetane_number": (0.0, 5.0),
    "density_min_kgm3": (0.0, 15.0),
    "density_max_kgm3": (0.0, 15.0),
}

#: Constraint type -> (needs limit, value kind, value range). Value kind None means no value.
CONSTRAINT_TYPES = {
    "min_quality_margin": (True, "number", None),
    "max_changes": (False, "int", (0, 2)),
    "forbid_additive": (False, None, None),
    "max_outflow_utilization": (False, "number", (0.3, 1.0)),
    "constant_plans_only": (False, None, None),
    "min_hours_to_violation": (False, "number", (0.0, 48.0)),
    "require_not_fragile": (False, None, None),
}


class ContractViolation(ValueError):
    """A model answer that does not satisfy the contract. Never interpreted further."""

    def __init__(self, path: str, message: str):
        super().__init__(f"{path}: {message}")
        self.path = path


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _text(value, path: str, limit: int) -> str:
    if not isinstance(value, str):
        raise ContractViolation(path, "ожидается строка")
    return value.strip()[:limit]


def _code(value, path: str) -> str:
    if not isinstance(value, str) or not _CODE.match(value):
        raise ContractViolation(path, "код причины: [a-z0-9_]{1,40}")
    return value


def _list(value, path: str, limit: int) -> list:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ContractViolation(path, "ожидается список")
    return value[:limit]


def _object(raw, path: str, allowed: set[str], required: set[str]) -> dict:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ContractViolation(path, f"не JSON: {exc.msg}") from exc
    if not isinstance(raw, dict):
        raise ContractViolation(path, "ожидается JSON-объект")
    extra = sorted(set(raw) - allowed)
    if extra:
        raise ContractViolation(path, f"неизвестные поля {extra}")
    missing = sorted(required - set(raw))
    if missing:
        raise ContractViolation(path, f"нет обязательных полей {missing}")
    return raw


def extract_json_object(text: str) -> dict | None:
    """Local repair: the single JSON object in a text answer, or None when there is not exactly one."""
    if not isinstance(text, str):
        return None
    stripped = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        value = json.loads(stripped)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        pass
    decoder, found, index = json.JSONDecoder(), [], 0
    while True:
        start = stripped.find("{", index)
        if start < 0:
            break
        try:
            value, end = decoder.raw_decode(stripped, start)
        except json.JSONDecodeError:
            index = start + 1
            continue
        if isinstance(value, dict):
            found.append(value)
        index = end
    return found[0] if len(found) == 1 else None


@dataclass(frozen=True)
class AgentConstraint:
    """A narrowing filter computed by code over plans that already passed the gate."""

    type: str
    limit: str | None = None
    value: float | None = None

    def key(self) -> tuple:
        return (self.type, self.limit, self.value)

    def to_dict(self) -> dict:
        out = {"type": self.type}
        if self.limit is not None:
            out["limit"] = self.limit
        if self.value is not None:
            out["value"] = self.value
        return out


def parse_constraint(raw, path: str = "constraint") -> AgentConstraint:
    data = _object(raw, path, {"type", "limit", "value"}, {"type"})
    kind = data["type"]
    if kind not in CONSTRAINT_TYPES:
        raise ContractViolation(f"{path}.type", f"неизвестный тип {kind!r}")
    needs_limit, value_kind, bounds = CONSTRAINT_TYPES[kind]
    limit = data.get("limit")
    if needs_limit:
        if limit not in MARGIN_RANGES:
            raise ContractViolation(f"{path}.limit", f"ожидается одно из {sorted(MARGIN_RANGES)}")
        bounds = MARGIN_RANGES[limit]
    elif limit is not None:
        raise ContractViolation(f"{path}.limit", "у этого типа нет предела")
    value = data.get("value")
    if value_kind is None:
        if value is not None:
            raise ContractViolation(f"{path}.value", "у этого типа нет значения")
        return AgentConstraint(kind)
    if not _is_number(value) or (value_kind == "int" and int(value) != value):
        raise ContractViolation(f"{path}.value", "ожидается конечное число" if value_kind == "number" else "ожидается целое")
    low, high = bounds
    if not low <= value <= high:
        raise ContractViolation(f"{path}.value", f"вне допустимого диапазона [{low:g}, {high:g}]")
    return AgentConstraint(kind, limit, int(value) if value_kind == "int" else float(value))


def parse_constraints(raw, path: str = "constraints") -> tuple[list[AgentConstraint], list[dict]]:
    """Accept valid constraints one by one; an invalid item is rejected without discarding the rest."""
    accepted, rejected, seen = [], [], set()
    items = raw if isinstance(raw, list) else [raw] if raw is not None else []
    for index, item in enumerate(items):
        if index >= MAX_CONSTRAINTS:
            rejected.append({"index": index, "error": f"больше {MAX_CONSTRAINTS} ограничений"})
            continue
        try:
            constraint = parse_constraint(item, f"{path}[{index}]")
        except ContractViolation as exc:
            rejected.append({"index": index, "error": str(exc)})
            continue
        if constraint.key() not in seen:
            seen.add(constraint.key())
            accepted.append(constraint)
    return accepted, rejected


@dataclass(frozen=True)
class ReasonItem:
    code: str
    text: str
    candidate_id: str | None = None

    def to_dict(self) -> dict:
        return {"code": self.code, "text": self.text, "candidate_id": self.candidate_id}


@dataclass(frozen=True)
class Opinion:
    """Answer of a specialist agent. `candidate_verdicts[id] == REJECT` is a veto of that plan."""

    role: str
    verdict: str
    risk_level: str
    reasons: tuple[ReasonItem, ...]
    confidence: float
    requested_checks: tuple[str, ...] = ()
    proposed_constraints: tuple[AgentConstraint, ...] = ()
    rejected_constraints: tuple[dict, ...] = ()
    preferred_candidates: tuple[str, ...] = ()
    candidate_verdicts: dict = field(default_factory=dict)
    evidence_refs: tuple[str, ...] = ()
    valid: bool = True

    @property
    def vetoed(self) -> tuple[str, ...]:
        return tuple(sorted(cid for cid, verdict in self.candidate_verdicts.items() if verdict == "REJECT"))

    @classmethod
    def unknown(cls, role: str, code: str, text: str) -> "Opinion":
        return cls(role, "UNKNOWN", "unknown", (ReasonItem(code, text[:MAX_REASON_TEXT]),), 0.0, valid=False)

    def to_dict(self) -> dict:
        return {"role": self.role, "verdict": self.verdict, "risk_level": self.risk_level,
                "reasons": [r.to_dict() for r in self.reasons], "confidence": self.confidence,
                "requested_checks": list(self.requested_checks),
                "proposed_constraints": [c.to_dict() for c in self.proposed_constraints],
                "rejected_constraints": list(self.rejected_constraints),
                "preferred_candidates": list(self.preferred_candidates),
                "candidate_verdicts": dict(sorted(self.candidate_verdicts.items())),
                "evidence_refs": list(self.evidence_refs), "valid": self.valid}


OPINION_FIELDS = {"verdict", "risk_level", "reasons", "requested_checks", "proposed_constraints",
                  "preferred_candidates", "candidate_verdicts", "confidence", "evidence_refs"}


def parse_opinion(role: str, raw, *, candidates, evidence) -> Opinion:
    """Parse a specialist answer against the candidates it was asked about and the evidence it saw.

    A verdict that commits (ACCEPT or REJECT) without any reference to evidence actually obtained in this
    conversation is downgraded to UNKNOWN: a model may not decide from nothing.
    """
    if role not in ("quality", "reliability"):
        raise ContractViolation("role", f"ожидается quality или reliability, получено {role!r}")
    data = _object(raw, "opinion", OPINION_FIELDS, {"verdict", "risk_level", "reasons", "confidence"})
    verdict = data["verdict"]
    if verdict not in VERDICTS:
        raise ContractViolation("opinion.verdict", f"ожидается одно из {VERDICTS}")
    risk = data["risk_level"]
    if risk not in RISK_LEVELS:
        raise ContractViolation("opinion.risk_level", f"ожидается одно из {RISK_LEVELS}")
    confidence = data["confidence"]
    if not _is_number(confidence) or not 0.0 <= confidence <= 1.0:
        raise ContractViolation("opinion.confidence", "ожидается число в [0, 1]")
    allowed = set(candidates)
    reasons = []
    for index, item in enumerate(_list(data["reasons"], "opinion.reasons", MAX_REASONS)):
        path = f"opinion.reasons[{index}]"
        item = _object(item, path, {"code", "text", "candidate_id"}, {"code", "text"})
        candidate = item.get("candidate_id")
        if candidate is not None and candidate not in allowed:
            candidate = None
        reasons.append(ReasonItem(_code(item["code"], f"{path}.code"),
                                  _text(item["text"], f"{path}.text", MAX_REASON_TEXT), candidate))
    if not reasons:
        raise ContractViolation("opinion.reasons", "нужна хотя бы одна причина")
    checks = tuple(_text(c, "opinion.requested_checks", 60)
                   for c in _list(data.get("requested_checks"), "opinion.requested_checks", MAX_REQUESTED_CHECKS))
    accepted, rejected = parse_constraints(_list(data.get("proposed_constraints"), "opinion.proposed_constraints",
                                                 MAX_CONSTRAINTS + 2), "opinion.proposed_constraints")
    preferred = tuple(c for c in _list(data.get("preferred_candidates"), "opinion.preferred_candidates", MAX_PREFERRED)
                      if isinstance(c, str) and c in allowed)
    raw_verdicts = data.get("candidate_verdicts") or {}
    if not isinstance(raw_verdicts, dict):
        raise ContractViolation("opinion.candidate_verdicts", "ожидается объект")
    verdicts = {}
    for candidate, value in list(raw_verdicts.items())[:MAX_CANDIDATE_VERDICTS]:
        if value not in VERDICTS:
            raise ContractViolation(f"opinion.candidate_verdicts.{candidate}", f"ожидается одно из {VERDICTS}")
        if candidate in allowed:
            verdicts[candidate] = value
    known = set(evidence)
    refs = tuple(dict.fromkeys(r for r in _list(data.get("evidence_refs"), "opinion.evidence_refs", MAX_EVIDENCE)
                               if isinstance(r, str) and r in known))
    if verdict in ("ACCEPT", "REJECT") and not refs:
        verdict, risk = "UNKNOWN", "unknown"
        verdicts = {k: ("UNKNOWN" if v in ("ACCEPT", "REJECT") else v) for k, v in verdicts.items()}
        reasons.append(ReasonItem("ungrounded_verdict", "Вердикт без ссылки на полученные данные понижен до UNKNOWN"))
    elif verdict == "REJECT" and not verdicts:
        verdicts = {candidate: "REJECT" for candidate in sorted(allowed)}
    return Opinion(role, verdict, risk, tuple(reasons[:MAX_REASONS + 1]), float(confidence), checks,
                   tuple(accepted), tuple(rejected), preferred, verdicts, refs)


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
    """Bounds of one agentic decision. Small by default: the deterministic core does the work."""

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
    max_tokens: int = 2048
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
    """Short JSON text for traces; truncated with an explicit marker."""
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    except (TypeError, ValueError):
        text = str(value)
    return text if len(text) <= limit else text[: max(0, limit - 1)] + "…"


@dataclass(frozen=True)
class AgentTraceEvent:
    """One compact audit record. No hidden reasoning, no prompt text, no credentials."""

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
