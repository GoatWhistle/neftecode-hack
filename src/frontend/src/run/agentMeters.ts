import type { AgenticBudget } from "../types";
import type { AgentEvent, StageFacts } from "./types";
import { finishText } from "./agentVocab";

export const FALLBACK_TEXT: Record<string, string> = {
  "budget:llm_calls": "Лимит обращений к модели исчерпан",
  "budget:timeout": "Истекло время, отведённое агентам"
};

export const ROLE_TEXT: Record<string, string> = {
  orchestrator: "оркестратор",
  quality: "агент качества",
  reliability: "агент надёжности"
};

export const BUDGET_CELL_MAX = 20;

export interface ProviderBand {
  provider: string;
  model: string;
  deterministic: boolean;
  known: boolean;
}

export interface CallMeter {
  latency: string;
  usage: string;
  finish: string;
  measured: boolean;
}

export interface BudgetRow {
  role: string;
  label: string;
  used: number;
  limit: number | null;
  exact: boolean;
  spent: boolean;
}

export function fallbackText(decision: string | undefined): string {
  if (!decision) return "Откат без пометки причины";
  if (FALLBACK_TEXT[decision]) return FALLBACK_TEXT[decision];
  if (decision.startsWith("llm_error")) return "Модель не ответила";
  return `Откат: ${decision}`;
}

export function providerBand(facts: StageFacts | undefined, agentic: {
  provider?: string | null;
  model?: string | null;
  deterministic_policy?: boolean;
} | null): ProviderBand | null {
  const provider = facts?.provider ?? agentic?.provider ?? null;
  const model = facts?.model ?? agentic?.model ?? null;
  const flag = facts?.deterministic_policy ?? agentic?.deterministic_policy;
  if (provider === null && model === null && flag === undefined) return null;
  const deterministic = flag === true || provider === "scripted";
  return {
    provider: provider ?? "провайдер не передан",
    model: model ?? "модель не передана",
    deterministic,
    known: provider !== null || model !== null
  };
}

function seconds(ms: number): string {
  if (ms < 1000) return `${ms} мс`;
  return `${(ms / 1000).toFixed(1).replace(".", ",")} с`;
}

function tokens(total: number): string {
  return `${total.toLocaleString("ru-RU")} ток.`;
}

export function callMeter(event: AgentEvent, deterministic: boolean): CallMeter {
  const latency = event.latency_ms;
  const total = event.usage?.["total_tokens"];
  const measured = typeof latency === "number" && latency > 0;
  if (deterministic || (latency === 0 && (total === 0 || total === undefined))) {
    return { latency: "политика, без вызова модели", usage: "", finish: "", measured: false };
  }
  return {
    latency: measured ? seconds(latency) : "длительность не передана",
    usage: typeof total === "number" && total > 0 ? tokens(total) : "токенов не передано",
    finish: finishText(event.decision),
    measured
  };
}

export function budgetRows(events: AgentEvent[], facts: StageFacts | undefined,
  budget: AgenticBudget | undefined): BudgetRow[] {
  const sent = facts?.budget_limits ?? {};
  const byRole = budget?.llm_calls_by_role;
  const live: Record<string, number> = {};
  for (const event of events) {
    if (event.kind !== "llm_call") continue;
    live[event.agent] = (live[event.agent] ?? 0) + 1;
  }
  const roles = Object.keys(ROLE_TEXT).filter((role) => live[role] !== undefined
    || (byRole && byRole[role] !== undefined));
  return roles.map((role) => {
    const exact = byRole !== undefined && byRole[role] !== undefined;
    const limitKey = role === "orchestrator" ? "max_steps" : "specialist_max_calls";
    const sentLimit = sent[limitKey] ?? sent[role];
    const used = exact ? (byRole?.[role] ?? 0) : live[role] ?? 0;
    const limit = typeof sentLimit === "number" ? sentLimit : null;
    return { role, label: ROLE_TEXT[role] ?? role, used, limit, exact,
      spent: limit !== null && used >= limit };
  });
}

function row(role: string, label: string, used: number | undefined, limit: unknown,
  exact: boolean): BudgetRow | null {
  if (used === undefined) return null;
  const bound = typeof limit === "number" ? limit : null;
  return { role, label, used, limit: bound, exact, spent: bound !== null && used >= bound };
}

export function spendRows(facts: StageFacts | undefined,
  budget: AgenticBudget | undefined): BudgetRow[] {
  if (budget === undefined) return [];
  const sent = facts?.budget_limits ?? {};
  const consults = budget.consults;
  const consultsUsed = consults === undefined
    ? undefined
    : Object.values(consults).reduce((sum, value) => sum + value, 0);
  const rows = [
    row("consults", "консультаций специалистов", consultsUsed, sent["max_specialist_consults"], true),
    row("replans", "повторных поисков", budget.replans, sent["max_replans"], true),
    row("robustness", "проверок устойчивости", budget.robustness_runs, sent["max_robustness_runs"], true)
  ];
  return rows.filter((item): item is BudgetRow => item !== null);
}

export function totalCalls(events: AgentEvent[], budget: AgenticBudget | undefined): BudgetRow | null {
  const declared = budget?.max_llm_calls;
  const exact = typeof budget?.llm_calls === "number";
  const used = exact ? (budget?.llm_calls ?? 0) : events.filter((e) => e.kind === "llm_call").length;
  if (used === 0 && !exact) return null;
  const limit = typeof declared === "number" ? declared : null;
  return { role: "all", label: "всего обращений", used, limit, exact,
    spent: limit !== null && used >= limit };
}
