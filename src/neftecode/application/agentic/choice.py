"""Пометки агентного этапа в блоке `choice` (P2).

Вето роли и принятые ограничения агентов исключают кандидатов из допустимого пула до
детерминированного ранжирования. Здесь это отражается в карточках кандидатов той же записи;
расчёт и выбор не меняются. Дорогие ограничения (горизонт, устойчивость) читаются только из
уже посчитанного в сессии: не проверенное так и называется, а не выдаётся за нарушение.
"""

import copy

from .session_support import LOOKAHEAD_CONSTRAINT_CAP

EXPENSIVE = ("min_hours_to_violation", "require_not_fragile")


def _constraint_text(constraint) -> str:
    parts = [constraint.type]
    if constraint.limit is not None:
        parts.append(str(constraint.limit))
    if constraint.value is not None:
        parts.append(f"{constraint.value:g}")
    return " ".join(parts)


def _unmet(session, candidate_id: str) -> tuple[list[dict], list[dict]]:
    """(нарушенные, не проверенные) принятые ограничения агентов для кандидата."""
    unmet, unchecked = [], []
    for constraint in session.constraints:
        entry = {"type": constraint.type, "limit": constraint.limit, "value": constraint.value,
                 "text": _constraint_text(constraint)}
        if constraint.type not in EXPENSIVE:
            if not session._satisfies(candidate_id, constraint):
                unmet.append(entry)
            continue
        if constraint.type == "min_hours_to_violation":
            info = session._lookahead.get(candidate_id)
            if info is None:
                unchecked.append({**entry, "why": (f"горизонт считается только для первых "
                                                   f"{LOOKAHEAD_CONSTRAINT_CAP} кандидатов по порядку")})
            elif not info.get("available"):
                unmet.append({**entry, "observed": None, "why": "расчёт за горизонтом недоступен"})
            else:
                reach = info.get("hours_to_violation")
                if reach is not None and reach < constraint.value - 1e-9:
                    unmet.append({**entry, "observed": reach})
        else:
            info = session._robustness.get(candidate_id)
            if info is None:
                unchecked.append({**entry, "why": "устойчивость для него не считалась в этой сессии"})
            elif not (info.get("available") is True and info.get("fragile") is False):
                unmet.append({**entry, "observed": info.get("fragile")})
    return unmet, unchecked


def annotate_choice(result: dict, session) -> dict:
    """Только для результата, сформированного агентным этапом: итог ядра (legacy) не меняется."""
    choice = result.get("choice")
    if not choice or not (session.vetoes or session.constraints):
        return result
    result = {**result, "choice": copy.deepcopy(choice)}
    choice = result["choice"]
    allowed = set(session.allowed_ids())
    legacy_id = session.legacy_plan_id
    known = {card["candidate_id"] for card in choice.get("candidates", [])}
    if legacy_id is not None and legacy_id not in known and legacy_id in session.evaluations \
            and legacy_id != choice.get("selected_id"):
        evaluation = session.evaluations[legacy_id]
        choice.setdefault("candidates", []).append(session.maker._card(
            evaluation, "excluded", session.maker._gate_reasons(evaluation, choice.get("decision_id"))))
    for card in choice.get("candidates", []):
        cid = card["candidate_id"]
        if cid == choice.get("selected_id") or cid not in session.evaluations:
            continue
        reasons = []
        if cid in session.vetoes:
            roles = sorted(session.vetoes[cid])
            reasons.append({"category": "agent_veto", "stage": "agents",
                            "text": f"Исключён вето роли: {', '.join(roles)}",
                            "rule": {"id": "agent_veto", "value": None, "observed": None,
                                     "source": "agentic.vetoed_candidates", "roles": roles}})
        elif session.passes(cid) and cid not in allowed:
            unmet, unchecked = _unmet(session, cid)
            if unmet:
                reasons.append({"category": "agent_constraint", "stage": "agents",
                                "text": "Не проходит принятое ограничение агента: "
                                        + "; ".join(u["text"] for u in unmet),
                                "rule": {"id": "agent_constraint", "value": None, "observed": None,
                                         "source": "agentic.constraints_applied", "constraints": unmet}})
            elif unchecked:
                reasons.append({"category": "agent_constraint", "stage": "agents",
                                "text": "Исключён до проверки ограничения агента: "
                                        + "; ".join(f"{u['text']} ({u['why']})" for u in unchecked),
                                "rule": {"id": "agent_constraint_unchecked", "value": None, "observed": None,
                                         "source": "agentic.constraints_applied", "constraints": unchecked}})
        if not reasons:
            continue
        card["reasons"] = [r for r in card["reasons"]
                           if r["category"] not in ("not_in_final_pool", "policy_not_selected")] + reasons
        card["verdict"] = "excluded"

    selected_id = choice.get("selected_id")
    choice["agents"] = {
        "vetoed": sorted(session.vetoes),
        "constraints": [c.to_dict() for c in session.constraints],
        "allowed": len(allowed),
        "legacy_plan_id": legacy_id,
        "legacy_excluded": legacy_id is not None and legacy_id not in allowed,
        "selected_changed": selected_id is not None and legacy_id is not None and selected_id != legacy_id,
        "note": ("Влияние на выбор установлено, только если выбор ядра без агентов исключён агентами; "
                 "иначе принятое ограничение не изменило итог."),
    }
    if choice["agents"]["legacy_excluded"] and selected_id is not None:
        choice["determined_by"] = [{"stage": "agents",
                                    "text": f"План ядра {legacy_id} исключён агентами; выбран лучший из оставшихся",
                                    "candidate_ids": [legacy_id]}] + list(choice.get("determined_by") or [])
    choice["pool"] = {**choice.get("pool", {}), "allowed_by_agents": len(allowed)}
    return result
