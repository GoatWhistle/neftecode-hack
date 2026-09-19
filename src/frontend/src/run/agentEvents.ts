import type { AgentEvent } from "./types";

export const AGENT_NAMES: Record<string, string> = {
  orchestrator: "оркестратор",
  quality: "агент качества",
  reliability: "агент надёжности",
  system: "детерминированный код",
  data: "агент данных"
};

export const KIND_TEXT: Record<string, string> = {
  llm_call: "обращение к модели",
  consult: "консультация специалиста",
  tool: "вызов инструмента",
  final: "ответ агента",
  resolution: "мнение оформлено",
  guard: "перепроверка кодом"
};

export interface AgentGroup {
  key: string;
  agent: string;
  title: string;
  events: AgentEvent[];
}

export function groupEvents(events: AgentEvent[]): AgentGroup[] {
  const groups: AgentGroup[] = [];
  let current: AgentGroup | null = null;

  for (const event of events) {
    if (event.kind === "consult") {
      current = {
        key: `consult-${event.seq}`,
        agent: event.tool_name === "ask_reliability_agent" ? "reliability" : "quality",
        title: `Оркестратор спрашивает: ${event.tool_name ?? "специалиста"}`,
        events: [event]
      };
      groups.push(current);
      continue;
    }
    if (event.agent === "orchestrator" && current !== null && event.kind !== "llm_call") {
      current = null;
    }
    if (current !== null && (event.agent === current.agent || event.agent === "system")) {
      current.events.push(event);
      if (event.kind === "resolution") current = null;
      continue;
    }
    const last = groups[groups.length - 1];
    if (last && last.key.startsWith("orchestrator") && last.agent === event.agent) {
      last.events.push(event);
      continue;
    }
    groups.push({
      key: `orchestrator-${event.seq}`,
      agent: event.agent,
      title: `${AGENT_NAMES[event.agent] ?? event.agent} работает`,
      events: [event]
    });
  }
  return groups;
}

export function summarize(event: AgentEvent): string {
  if (event.kind === "llm_call") {
    const usage = event.usage?.["total_tokens"];
    const latency = event.latency_ms;
    const parts: string[] = [];
    if (typeof latency === "number" && latency > 0) parts.push(`${latency} мс`);
    if (typeof usage === "number" && usage > 0) parts.push(`${usage} токенов`);
    return parts.length > 0 ? parts.join(", ") : "счётчиков не передано";
  }
  if (event.kind === "consult") return event.tool_input_summary ?? "запрос без сводки";
  if (event.kind === "tool") return event.tool_name ?? "инструмент не назван";
  if (event.kind === "final") return event.decision ?? "ответ без пометки";
  if (event.kind === "guard") return `перепроверка: ${event.decision ?? "без пометки"}`;
  return event.decision ?? "";
}
