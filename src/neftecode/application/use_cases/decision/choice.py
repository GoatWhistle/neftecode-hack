"""Почему выбран этот вариант и что мешает при отказе (P2).

Блок собирается из того, что уже посчитано в этом запуске: пул оценок поиска, финальное
ранжирование, Gate каждого кандидата, упреждение за горизонтом, вето слабого отклика и
обязательной устойчивости, финальная перепроверка. Второго ранжировщика нет: причина
«допустим, но не выбран» выводится из того же правила `rank` и тех же чисел, что его
определили. Ссылки на проверки несут decision_id этого запуска и id кандидата внутри него.
"""

import math

from neftecode.domain.production.quantities import UNITS
from neftecode.domain.shared.primitives import PRODUCT_LIMITS
from ...services.comparison import COMPARISON_RULE, TIE_TEXT, why_not

CHOICE_VERSION = 1
MAX_CONSTRAINTS_PER_CANDIDATE = 6
MAX_REFUSAL_CANDIDATES = 3

SCOPE_NOTE = ("Сравнение только внутри пула, исследованного в этом запуске; глобальный минимум "
              "стоимости за его пределами не утверждается.")


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


class ChoiceMixin:

    def _constraint_meta(self, constraint_id: str) -> tuple[str | None, str | None]:
        """Единица и источник предела проверки; неизвестное остаётся None."""
        family, _, rest = constraint_id.partition(".")
        if family == "quality" and rest in PRODUCT_LIMITS:
            quantity = self.scenario.product.limits.get(rest)
            return UNITS.get(PRODUCT_LIMITS[rest][0]), (quantity.source if quantity is not None else None)
        if family == "control":
            name = rest.split(".")[0]
            for stage in self.scenario.stages.values():
                spec = stage.controls.get(name)
                if spec is not None:
                    return spec["max"].unit, spec["max"].source
        if family == "outflow":
            try:
                tank = self.scenario.tank(rest)
            except Exception:
                return None, None
            return tank.max_outflow.unit, tank.max_outflow.source
        if family == "inventory" and "." not in rest and rest != "availability":
            return "т", None
        return None, None

    def _check_refs(self, evaluation, decision_id: str | None) -> list[dict]:
        """Все нарушенные и неизвестные ограничения кандидата: по одной записи на constraint_id
        с первым моментом и числом таких точек — не первая причина вместо всех."""
        grouped: dict[str, dict] = {}
        for check in evaluation.gate.checks:
            if check.status not in ("fail", "unknown"):
                continue
            key = (check.constraint_id, check.status)
            entry = grouped.get(key)
            if entry is None:
                unit, source = self._constraint_meta(check.constraint_id)
                grouped[key] = {
                    "decision_id": decision_id, "candidate_id": evaluation.candidate.candidate_id,
                    "constraint_id": check.constraint_id, "status": check.status,
                    "time_hours": check.time_hours, "observed": check.observed, "limit": check.limit,
                    "unit": unit, "limit_source": source, "reason": check.reason, "points": 1,
                }
            else:
                entry["points"] += 1
        refs = sorted(grouped.values(), key=lambda r: (r["status"] != "fail",
                                                        r["time_hours"] if r["time_hours"] is not None else math.inf,
                                                        r["constraint_id"]))
        return refs

    @staticmethod
    def _figures(evaluation) -> dict:
        return {"production_t": evaluation.production_t, "cost_per_tonne": evaluation.cost_per_tonne,
                "severity_index": evaluation.severity_index, "changes": evaluation.candidate.changes}

    def _gate_reasons(self, evaluation, decision_id) -> list[dict]:
        refs = self._check_refs(evaluation, decision_id)
        reasons = []
        failed = [r for r in refs if r["status"] == "fail"]
        unknown = [r for r in refs if r["status"] == "unknown"]
        if failed:
            reasons.append({"category": "gate_fail", "stage": "search",
                            "text": f"Нарушен обязательный Gate: {len(failed)} огранич.",
                            "evidence": failed[:MAX_CONSTRAINTS_PER_CANDIDATE],
                            "evidence_total": len(failed)})
        if unknown:
            reasons.append({"category": "gate_unknown", "stage": "search",
                            "text": f"Проверка не выполнена (UNKNOWN): {len(unknown)} огранич.; "
                                    "неизвестное не считается выполненным",
                            "evidence": unknown[:MAX_CONSTRAINTS_PER_CANDIDATE],
                            "evidence_total": len(unknown)})
        return reasons

    def _policy_reason(self, evaluation, selected_eval, ranking: dict, by_id: dict) -> dict:
        """Допустимый, но не выбранный: какое правило политики решило, с его числами."""
        cid = evaluation.candidate.candidate_id
        hold_policy = (ranking or {}).get("hold_policy")
        if hold_policy:
            rule = {"id": "min_useful_gain", "value": hold_policy["min_useful_gain"],
                    "observed": hold_policy["gain"], "source": "scenario.policy.min_useful_gain",
                    "compared_with": hold_policy["overridden"]}
            policy = (f"выигрыш {hold_policy['gain']:.2%} меньше минимального полезного "
                      f"{hold_policy['min_useful_gain']:.0%} при том же выпуске: режим сохраняется")
            if hold_policy.get("overridden") == cid:
                return {"category": "policy_not_selected", "stage": "policy",
                        "text": f"Лучший по правилу, но {policy}", "rule": rule}
            best = by_id.get(hold_policy["overridden"])
            if best is None:
                behind = "уступает лучшему по правилу"
            else:
                behind = why_not(evaluation.to_dict(), self._figures(best))
                if behind == TIE_TEXT:
                    behind = (f"совпадает с {best.candidate.candidate_id} по всем критериям, порядок решил "
                              f"идентификатор")
                else:
                    behind = behind.replace("у выбранного плана", f"у {best.candidate.candidate_id}")
            return {"category": "policy_not_selected", "stage": "policy",
                    "text": (f"Лучший по правилу — {hold_policy['overridden']}, но {policy}. "
                             f"Относительно него: {behind}"), "rule": rule}
        tradeoff = (ranking or {}).get("reliability_tradeoff")
        if tradeoff and tradeoff.get("compared_with") == cid:
            return {"category": "policy_not_selected", "stage": "policy",
                    "text": ("Дешевле, но внутри допустимой разницы стоимости политика выбирает режим с меньшей "
                             "тяжестью или меньшим числом изменений"),
                    "rule": {"id": "severity_cost_tolerance_fraction",
                             "value": (ranking or {}).get("severity_cost_tolerance_fraction"),
                             "observed": tradeoff.get("cost_premium_fraction"),
                             "source": "scenario.policy.severity_cost_tolerance_fraction"}}
        if selected_eval is None:
            return {"category": "policy_not_selected", "stage": "policy",
                    "text": "Допустим, но не выбран; выбранный план в пуле не найден для сравнения",
                    "rule": {"id": "ranking", "value": None, "observed": None, "source": "rank"}}
        return {"category": "policy_not_selected", "stage": "policy",
                "text": why_not(evaluation.to_dict(), self._figures(selected_eval)),
                "rule": {"id": "ranking", "value": None, "observed": None, "source": "rank",
                         "order": list((ranking or {}).get("ranking") or ())}}

    def _card(self, evaluation, verdict: str, reasons: list[dict]) -> dict:
        return {"candidate_id": evaluation.candidate.candidate_id, **self._figures(evaluation),
                "verdict": verdict, "reasons": reasons}

    def _choice(self, *, status, decision_id, ranking, pool, examined, plan, evaluation, lookahead,
                vetoed, refusal) -> dict:
        examined = list(examined or ())
        by_id = {e.candidate.candidate_id: e for e in examined}
        for e in pool or ():
            by_id.setdefault(e.candidate.candidate_id, e)
        pool_ids = {e.candidate.candidate_id for e in pool or ()}
        vetoed = list(vetoed or ())
        vetoed_ids = {v["candidate_id"]: v for v in vetoed}
        selected_id = plan.plan_id if plan is not None else None
        selected_eval = evaluation if evaluation is not None else by_id.get(selected_id)
        # Gate-допустимые, но снятые сценарным пределом тяжести внутри rank.
        policy_rejected = {item["candidate_id"]: item for item in (ranking or {}).get("rejected", [])
                           if item.get("candidate_id") in by_id and by_id[item["candidate_id"]].feasible}

        def reasons_for(e) -> tuple[str, list[dict]]:
            cid = e.candidate.candidate_id
            if cid == selected_id:
                return "selected", []
            reasons = self._gate_reasons(e, decision_id)
            if cid in vetoed_ids:
                reasons.append(vetoed_ids[cid]["reason"])
            if not reasons and cid in policy_rejected:
                reasons.append({"category": "policy_limit", "stage": "policy",
                                "text": "; ".join(policy_rejected[cid].get("rejection_reasons") or ()),
                                "rule": {"id": "max_severity_index",
                                         "value": (ranking or {}).get("max_severity_index"),
                                         "observed": e.severity_index,
                                         "source": "scenario.policy.max_severity_index"}})
            if (lookahead or {}).get("switched") and cid == lookahead.get("initial_plan"):
                first = lookahead.get("initial") or {}
                reasons.append({"category": "lookahead", "stage": "lookahead",
                                "text": (f"За горизонтом нарушение через {first.get('hours_to_violation')} ч — раньше "
                                         f"запаса реакции {lookahead.get('min_reaction_hours')} ч; выбран план, "
                                         f"отодвигающий нарушение"),
                                "evidence": [{"decision_id": decision_id, "candidate_id": cid,
                                              "constraint_id": first.get("constraint"), "status": "fail",
                                              "time_hours": first.get("hours_to_violation"),
                                              "observed": first.get("observed"), "limit": first.get("limit"),
                                              "unit": self._constraint_meta(first.get("constraint") or "")[0],
                                              "limit_source": self._constraint_meta(first.get("constraint") or "")[1],
                                              "reason": "расчёт за горизонтом решения (lookahead)", "points": 1}]
                                if first.get("constraint") else [],
                                "rule": {"id": "min_reaction_hours", "value": lookahead.get("min_reaction_hours"),
                                         "observed": first.get("hours_to_violation"),
                                         "source": "scenario.policy.min_reaction_hours"}})
            if not reasons and cid in pool_ids and status != "refuse":
                reasons.append(self._policy_reason(e, selected_eval, ranking, by_id))
            if not reasons and e.feasible and cid not in pool_ids:
                reasons.append({"category": "not_in_final_pool", "stage": "search",
                                "text": ("Проходит Gate, но не вошёл в пул финального сравнения этого запуска "
                                         "(проверен в другом раунде поиска)"),
                                "rule": {"id": "search_round", "value": None, "observed": None,
                                         "source": "optimizer.rounds"}})
            verdict = "admissible_not_selected" if (reasons and all(
                r["category"] == "policy_not_selected" for r in reasons)) else "excluded"
            return verdict, reasons

        def card_of(cid: str) -> dict | None:
            e = by_id.get(cid)
            if e is None:
                return None
            verdict, reasons = reasons_for(e)
            return self._card(e, verdict, reasons)

        cards: dict[str, dict] = {}
        order: list[str] = []

        def add(cid: str | None) -> dict | None:
            if cid is None:
                return None
            if cid not in cards:
                card = card_of(cid)
                if card is None:
                    return None
                cards[cid] = card
                order.append(cid)
            return cards[cid]

        add(selected_id)
        hold = add("hold")
        for alt in (ranking or {}).get("alternatives", [])[:5]:
            add(alt.get("candidate_id"))
        for cid in vetoed_ids:
            add(cid)
        if (lookahead or {}).get("switched"):
            add(lookahead.get("initial_plan"))

        cheaper = None
        cheaper_count = 0
        reference = selected_eval.cost_per_tonne if selected_eval is not None else None
        if _finite(reference):
            lower = [e for e in by_id.values()
                     if _finite(e.cost_per_tonne) and e.cost_per_tonne < reference - 1e-9]
            cheaper_count = len(lower)
            if lower:
                cheapest = min(lower, key=lambda e: (e.cost_per_tonne, e.candidate.candidate_id))
                cheaper = add(cheapest.candidate.candidate_id)

        if selected_id is not None:
            cheaper_note = (None if cheaper is not None else
                            "Среди вариантов, рассчитанных в этом запуске, дешевле выбранного нет.")
        else:
            cheaper_note = "Решение не выдано: сравнивать стоимость не с чем."

        determined_by = []
        if selected_id is not None:
            if vetoed:
                determined_by.append({"stage": "final_veto",
                                      "text": "Предыдущий выбранный план отклонён финальной проверкой; выбран "
                                              "следующий допустимый по тому же правилу",
                                      "candidate_ids": [v["candidate_id"] for v in vetoed]})
            if (lookahead or {}).get("switched"):
                determined_by.append({"stage": "lookahead",
                                      "text": "Упреждение за горизонтом заменило первоначальный план",
                                      "candidate_ids": [lookahead.get("initial_plan")]})
            if (ranking or {}).get("hold_policy"):
                determined_by.append({"stage": "policy", "text": ranking.get("reason"),
                                      "candidate_ids": [ranking["hold_policy"]["overridden"]]})
            elif (ranking or {}).get("reliability_tradeoff"):
                determined_by.append({"stage": "policy", "text": ranking.get("reason"),
                                      "candidate_ids": [ranking["reliability_tradeoff"].get("compared_with")]})
            if not determined_by:
                determined_by.append({"stage": "ranking", "text": (ranking or {}).get("reason") or "",
                                      "candidate_ids": []})

        refusal_view = None
        if status == "refuse":
            kind = (refusal or {}).get("kind")
            stage = {"data": "data", "no_feasible_plan": "search", "computation_error": "search",
                     "final_recheck_failed": "final_recheck", "weak_response_failed": "final_veto",
                     "mandatory_robustness_failed": "final_veto", "agent_rejected": "agents"}.get(kind, "unknown")
            refusal_view = {"kind": kind, "stage": stage,
                            "agents_skipped": kind == "data",
                            "domain_impossibility_proven": kind in ("no_feasible_plan", "final_recheck_failed",
                                                                    "weak_response_failed",
                                                                    "mandatory_robustness_failed")}
            if kind != "data":
                ranked = sorted(examined, key=lambda e: e.key())
                for e in ranked[:MAX_REFUSAL_CANDIDATES]:
                    add(e.candidate.candidate_id)
                if (refusal or {}).get("plan_id"):
                    add(refusal["plan_id"])

        return {
            "version": CHOICE_VERSION,
            "decision_id": decision_id,
            "status": status,
            "selected_id": selected_id,
            "hold_id": hold["candidate_id"] if hold is not None else None,
            "hold_examined": hold is not None,
            "cheaper_id": cheaper["candidate_id"] if cheaper is not None else None,
            "cheaper_count": cheaper_count,
            "cheaper_note": cheaper_note,
            "determined_by": determined_by,
            "pool": {"examined": len(by_id), "admissible_final": len(pool_ids), "scope": SCOPE_NOTE},
            "candidates": [cards[cid] for cid in order],
            "rule": COMPARISON_RULE,
            "refusal": refusal_view,
        }
