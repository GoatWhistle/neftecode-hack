from collections.abc import Callable
from dataclasses import dataclass, field
import json

from neftecode.application.ports.llm import LLMClient, LLMError, LLMMessage, ToolSpec

from .budget import AgentBudget, BudgetExhausted
from .contracts import AgentSettings, AgentTraceEvent, ContractViolation, extract_json_object
from .tools import ToolRegistry

MAX_INVALID_FINALS = 2


@dataclass
class AgentTrace:
    events: list = field(default_factory=list)
    sink: Callable[[dict], None] | None = None

    def add(self, agent: str, step: int, kind: str, **values) -> AgentTraceEvent:
        event = AgentTraceEvent(len(self.events) + 1, agent, step, kind, **values)
        self.events.append(event)
        if self.sink is not None:
            self.sink(event.to_dict())
        return event

    def to_list(self) -> list[dict]:
        return [event.to_dict() for event in self.events]

    def tools_called(self, agent: str | None = None) -> list[str]:
        return [e.tool_name for e in self.events
                if e.kind == "tool" and e.tool_name and (agent is None or e.agent == agent)]


@dataclass
class LoopResult:
    final: object | None
    stop_reason: str
    calls: int
    evidence: tuple[str, ...] = ()
    error: LLMError | None = None


def run_tool_loop(*, role: str, llm: LLMClient, system_prompt: str, context_text: str, context_refs,
                  registry: ToolRegistry, allowlist, final_tool: ToolSpec,
                  parse_final: Callable[[object, tuple], object], max_calls: int, budget: AgentBudget,
                  settings: AgentSettings, trace: AgentTrace) -> LoopResult:
    messages = [LLMMessage("system", system_prompt), LLMMessage("user", context_text)]
    evidence = list(context_refs)
    invalid_finals = 0
    calls = 0
    for step in range(1, max_calls + 1):
        last = step == max_calls
        if last:
            messages.append(LLMMessage("user", f"Лимит шагов исчерпан: вызови только инструмент {final_tool.name}."))
        tools = [final_tool] if last else registry.specs(allowlist) + [final_tool]
        try:
            budget.take_call(role)
        except BudgetExhausted as exc:
            trace.add(role, step, "fallback", decision=f"budget:{exc.what}")
            return LoopResult(None, f"budget:{exc.what}", calls, tuple(evidence))
        calls += 1
        timeout = max(1.0, min(settings.request_timeout_s, budget.remaining_seconds()))
        try:
            response = llm.chat(messages, tools, max_tokens=settings.max_tokens, timeout_s=timeout)
        except LLMError as exc:
            trace.add(role, step, "fallback", decision=f"llm_error:{exc.kind}", provider=llm.provider, model=llm.model,
                      reason_codes=(str(exc.code)[:40],) if exc.code else (), tool_result_summary=str(exc)[:300])
            return LoopResult(None, f"llm_error:{exc.kind}", calls, tuple(evidence), exc)
        budget.add_usage(response.usage.to_dict())
        trace.add(role, step, "llm_call", provider=response.provider or llm.provider, model=response.model or llm.model,
                  latency_ms=int(response.latency_s * 1000), usage=response.usage.to_dict(),
                  decision=response.finish_reason)

        if response.tool_calls:
            kept = response.tool_calls[: settings.max_tool_calls_per_response]
            if len(kept) < len(response.tool_calls):
                trace.add(role, step, "tool", decision="extra_tool_calls_dropped",
                          reason_codes=("extra_tool_calls_dropped",))
            messages.append(LLMMessage("assistant", response.content, tool_calls=tuple(kept)))
            for call in kept:
                if call.name == final_tool.name:
                    try:
                        final = parse_final(call.arguments, tuple(evidence))
                    except ContractViolation as exc:
                        invalid_finals += 1
                        detail = json.dumps({"error": "invalid_final", "detail": str(exc)[:200]}, ensure_ascii=False)
                        messages.append(LLMMessage("tool", detail, tool_call_id=call.call_id))
                        trace.add(role, step, "final", tool_name=call.name, decision="invalid_final",
                                  reason_codes=("contract_violation",), tool_result_summary=str(exc)[:300])
                        continue
                    trace.add(role, step, "final", tool_name=call.name, decision="accepted")
                    return LoopResult(final, "final", calls, tuple(evidence))
                outcome = registry.execute(call.name, call.arguments, allowlist)
                if outcome.evidence_ref:
                    evidence.append(outcome.evidence_ref)
                messages.append(LLMMessage("tool", outcome.text, tool_call_id=call.call_id))
                trace.add(role, step, "tool", tool_name=call.name, tool_input_summary=outcome.input_summary,
                          tool_result_summary=outcome.result_summary, candidate_ids=outcome.candidate_ids,
                          decision="ok" if outcome.ok else "error",
                          reason_codes=() if outcome.ok else (outcome.error.split(":")[0][:40],))
            if invalid_finals >= MAX_INVALID_FINALS:
                return LoopResult(None, "invalid_final", calls, tuple(evidence))
            continue

        repaired = extract_json_object(response.content)
        problem = "ответ без вызова инструмента и без JSON-объекта"
        if repaired is not None:
            try:
                final = parse_final(repaired, tuple(evidence))
                trace.add(role, step, "final", decision="accepted_from_text", reason_codes=("local_repair",))
                return LoopResult(final, "final", calls, tuple(evidence))
            except ContractViolation as exc:
                problem = str(exc)
        invalid_finals += 1
        trace.add(role, step, "final", decision="invalid_final", reason_codes=("text_answer",),
                  tool_result_summary=problem[:300])
        if invalid_finals >= MAX_INVALID_FINALS:
            return LoopResult(None, "invalid_final", calls, tuple(evidence))
        messages.append(LLMMessage("assistant", response.content[:2000]))
        messages.append(LLMMessage("user", f"Ответ не принят: {problem[:200]}. Используй инструменты или вызови "
                                           f"{final_tool.name} с аргументами по схеме."))
    return LoopResult(None, "max_calls", calls, tuple(evidence))
