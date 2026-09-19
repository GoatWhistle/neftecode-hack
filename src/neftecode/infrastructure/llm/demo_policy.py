from collections.abc import Sequence

from neftecode.application.ports.llm import LLMMessage, LLMResponse, ToolSpec

from .scripted import PolicyLLM, call, context_of, respond, tool_results

THIN_SULFUR_MARGIN = 1.0


def _operating_margin(context: dict) -> float:
    margin = (context.get("limits") or {}).get("sulfur_operating_margin_mgkg") or {}
    value = margin.get("value") if isinstance(margin, dict) else None
    return float(value) if isinstance(value, (int, float)) else THIN_SULFUR_MARGIN


def _refs(results) -> list[str]:
    return [r["result"]["evidence_ref"] for r in results
            if isinstance(r["result"], dict) and r["result"].get("evidence_ref")][:10]


def quality_policy(messages: Sequence[LLMMessage]) -> LLMResponse:
    context = context_of(messages)
    candidate = context["candidates"][0]["id"]
    results = tool_results(messages)
    names = [r["name"] for r in results]
    if not names:
        return respond(call("get_quality_margins", candidate_id=candidate))
    margins = results[0]["result"].get("margins", {})
    margin = (margins.get("sulfur_mgkg") or {}).get("min_margin")
    refs = _refs(results)
    thin = _operating_margin(context)
    if margin is None:
        return respond(call("submit_opinion", verdict="UNKNOWN", risk_level="high", confidence=0.3,
                            evidence_refs=refs, reasons=[{"code": "sulfur_unknown", "text": "Запас по сере неизвестен"}]))
    if margin >= thin:
        return respond(call("submit_opinion", verdict="ACCEPT", risk_level="low", confidence=0.8, evidence_refs=refs,
                            candidate_verdicts={candidate: "ACCEPT"},
                            reasons=[{"code": "sulfur_margin_ok", "text": f"Запас по сере {margin} мг/кг",
                                      "candidate_id": candidate}]))
    if "get_forecast_and_uncertainty" not in names:
        return respond(call("get_forecast_and_uncertainty"), call("get_tank_projection", candidate_id=candidate))
    wanted = round(min(0.5, margin + 0.001), 3)
    return respond(call("submit_opinion", verdict="REVISE", risk_level="medium", confidence=0.6, evidence_refs=refs,
                        candidate_verdicts={candidate: "REVISE"},
                        reasons=[{"code": "thin_sulfur_margin", "text": f"Запас по сере {margin} мг/кг меньше "
                                                                         f"технологического {thin}", "candidate_id": candidate}],
                        proposed_constraints=[{"type": "min_quality_margin", "limit": "sulfur_mgkg", "value": wanted}]))


def reliability_policy(messages: Sequence[LLMMessage]) -> LLMResponse:
    candidate = context_of(messages)["candidates"][0]["id"]
    results = tool_results(messages)
    if not results:
        return respond(call("get_setpoint_changes", candidate_id=candidate))
    refs = _refs(results)
    changes = results[0]["result"].get("changes", 0)
    if changes == 0:
        return respond(call("submit_opinion", verdict="ACCEPT", risk_level="low", confidence=0.9, evidence_refs=refs,
                            candidate_verdicts={candidate: "ACCEPT"},
                            reasons=[{"code": "no_intervention", "text": "Режим не меняется", "candidate_id": candidate}]))
    if len(results) == 1:
        return respond(call("get_robustness", candidate_id=candidate))
    robustness = results[1]["result"]
    fragile = robustness.get("fragile")
    text = f"Изменений: {changes}; выдержано отклонений {robustness.get('held')} из {robustness.get('evaluated')}"
    return respond(call("submit_opinion", verdict="REVISE" if fragile else "ACCEPT",
                        risk_level="medium" if fragile else "low", confidence=0.7, evidence_refs=refs,
                        candidate_verdicts={candidate: "REVISE" if fragile else "ACCEPT"},
                        reasons=[{"code": "fragile_plan" if fragile else "robust_plan", "text": text,
                                  "candidate_id": candidate}]))


def orchestrator_policy(messages: Sequence[LLMMessage]) -> LLMResponse:
    context = context_of(messages)
    legacy = context.get("legacy", {})
    shortlist = [c["id"] for c in context.get("candidates", [])]
    results = tool_results(messages)
    by_name = {}
    for result in results:
        by_name.setdefault(result["name"], []).append(result["result"])
    refs = _refs(results) or ["context:legacy"]

    def finalize(action, codes, summary, candidate=None):
        arguments = {"action": action, "reason_codes": codes, "summary": summary, "evidence_refs": refs}
        if candidate:
            arguments["candidate_id"] = candidate
        return respond(call("finalize", **arguments))

    if "rank_allowed" in by_name:
        ranked = by_name["rank_allowed"][-1]
        if ranked.get("selected") is None:
            return finalize("keep_legacy", ["no_allowed_plan"], "Новых допустимых планов нет: остаётся итог детерминированного контура")
        if "ask_reliability_agent" not in by_name:
            return respond(call("ask_reliability_agent", candidate_ids=[ranked["selected"]]))
        return finalize("select", ["best_allowed_after_review"], "Выбран лучший допустимый план после проверок",
                        ranked["selected"])
    if "search_candidates" in by_name:
        return respond(call("rank_allowed"))
    target = legacy.get("selected") or (shortlist[0] if shortlist else None)
    if target is None:
        if "search_candidates" not in by_name:
            return respond(call("search_candidates", constraints=[]))
        return finalize("keep_legacy", ["no_feasible_confirmed"], "Допустимых планов не найдено: отказ сохраняется")
    if "ask_quality_agent" not in by_name:
        return respond(call("ask_quality_agent", candidate_ids=[target], focus="запас качества выбранного плана"))
    quality = by_name["ask_quality_agent"][-1].get("opinion", {})
    if quality.get("verdict") == "REVISE" and quality.get("proposed_constraints"):
        return respond(call("search_candidates", constraints=quality["proposed_constraints"]))
    if quality.get("verdict") == "REJECT":
        return respond(call("rank_allowed"))
    if "ask_reliability_agent" not in by_name:
        return respond(call("ask_reliability_agent", candidate_ids=[target]))
    return finalize("keep_legacy", ["specialists_agree"], "Специалисты подтвердили вариант детерминированного контура")


def demo_policy(role: str, messages: Sequence[LLMMessage], tools: Sequence[ToolSpec]) -> LLMResponse:
    if role == "quality":
        return quality_policy(messages)
    if role == "reliability":
        return reliability_policy(messages)
    return orchestrator_policy(messages)


def demo_llm() -> PolicyLLM:
    return PolicyLLM(demo_policy, model="demo-policy")
