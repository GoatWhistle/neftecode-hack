"""Readable rendering of a compact agent trace for operators, auditors and the jury."""

_KIND_ICON = {"tool": "→", "consult": "⇢", "final": "■", "resolution": "◆", "guard": "✔", "fallback": "✖"}


def _step(event: dict) -> str | None:
    kind, agent = event.get("kind"), event.get("agent", "")
    if kind == "llm_call":
        return None
    ids = ", ".join(event.get("candidate_ids", []))
    codes = ", ".join(event.get("reason_codes", []))
    if kind == "tool":
        name = event.get("tool_name")
        status = "" if event.get("decision") == "ok" else f" — ошибка: {codes}"
        if name and name.startswith("ask_"):
            return f"{agent:12s} ← {name}: ответ получен{status}"
        target = f"({ids})" if ids else ""
        if name == "search_candidates":
            target = f"({event.get('tool_input_summary', '')})"
        return f"{agent:12s} → {name}{target}{status}"
    if kind == "consult":
        return f"{agent:12s} ⇢ {event.get('tool_name')}({ids})"
    if kind == "final":
        return f"{agent:12s} ■ {event.get('tool_name') or 'ответ'}: {event.get('decision')}"
    if kind == "resolution":
        detail = f" [{ids}]" if ids else ""
        return f"{'code':12s} ◆ {event.get('decision')}{detail}" + (f" ({codes})" if codes else "")
    if kind == "guard":
        return f"{'code':12s} ✔ независимая проверка Gate: {event.get('decision')}{' [' + ids + ']' if ids else ''}"
    if kind == "fallback":
        return f"{agent:12s} ✖ {event.get('decision')}"
    return None


def render_agent_trace(decision: dict) -> list[str]:
    """Lines describing what the agents did and how code resolved it; empty for a deterministic decision."""
    info = decision.get("agentic")
    if not info:
        return []
    lines = [f"провайдер: {info.get('provider')} / {info.get('model')}",
             f"детерминированный контур: {info.get('legacy_status')} (decision_id {info.get('legacy_decision_id')})"]
    optimizer = next((t for t in decision.get("trace", []) if t.get("agent") == "optimizer"), None)
    if optimizer:
        feasible = sum(r.get("feasible", 0) for r in optimizer.get("rounds", []))
        lines.append(f"поиск: оценено {optimizer.get('evaluated')} планов, прошли Gate {feasible}")
    step = next((t for t in decision.get("trace", []) if t.get("agent") == "agentic"), None)
    if step:
        lines.append(f"после агентов: оценено {step.get('evaluated')}, допустимо с ограничениями {step.get('allowed')}")
    lines += [line for line in (_step(e) for e in info.get("trace", [])) if line]
    selected = (decision.get("selected_plan") or {}).get("plan_id")
    budget = info.get("budget") or {}
    lines.append(f"итог: {decision.get('status')}{' ' + selected if selected else ''}; outcome={info.get('outcome')}"
                 + (f"; fallback={info.get('fallback_reason')}" if info.get("fallback_reason") else "")
                 + f"; вызовов LLM {budget.get('llm_calls', 0)}")
    if info.get("constraints_applied"):
        lines.append(f"принятые ограничения: {info['constraints_applied']}")
    if decision.get("gate"):
        lines.append(f"Gate выбранного плана: {'PASS' if decision['gate']['feasible'] else 'FAIL'}")
    robustness = decision.get("robustness")
    if robustness:
        lines.append(f"устойчивость: выдержано {robustness['held']} из {robustness['perturbations_evaluated']}"
                     f"{' — хрупкий' if robustness['fragile'] else ''}")
    return lines
