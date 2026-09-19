from dataclasses import dataclass, field

from .contract_primitives import (CONSTRAINT_TYPES, ContractViolation, MARGIN_RANGES, MAX_CANDIDATE_VERDICTS,
                                  MAX_CONSTRAINTS, MAX_EVIDENCE, MAX_PREFERRED, MAX_REASONS, MAX_REASON_TEXT,
                                  MAX_REQUESTED_CHECKS, RISK_LEVELS, VERDICTS,
                                  _code, _is_number, _list, _object, _text)


@dataclass(frozen=True)
class AgentConstraint:

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
