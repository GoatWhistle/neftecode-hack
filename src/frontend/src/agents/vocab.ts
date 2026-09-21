import type { Agentic, AgentOpinion, ProposedConstraint, ScreenPayload } from "../types";
import { CONSTRAINT_TEXT } from "../run/agentVocab";

export type CardKey = "orchestrator" | "quality" | "reliability";

export type CardTone = "idle" | "live" | "done" | "neutral" | "skipped" | "broken";

export interface ConstraintLine {
  key: string;
  label: string;
  detail: string | null;
  applied: boolean;
}

export interface EvidenceLine {
  key: string;
  text: string;
}

export interface AgentCardModel {
  key: CardKey;
  title: string;
  tone: CardTone;
  state: string;
  checked: string;
  concluded: string;
  effect: string;
  invalid: boolean;
  constraints: ConstraintLine[];
  evidence: EvidenceLine[];
  tech: string[];
}

export interface ContributionModel {
  cards: AgentCardModel[];
  headline: string;
  running: boolean;
  absent: string | null;
}

export const ROLE_TITLE: Record<CardKey, string> = {
  orchestrator: "Оркестратор",
  quality: "Агент качества",
  reliability: "Агент надёжности"
};

export const VERDICT_TEXT: Record<string, string> = {
  ACCEPT: "принять план",
  REVISE: "доработать план",
  REJECT: "отклонить план",
  ABSTAIN: "воздержаться"
};

export const OUTCOME_TEXT: Record<string, string> = {
  selected: "выбрал план",
  confirmed_legacy: "подтвердил исходный",
  refused: "отказал",
  fallback: "сбой, запасной путь",
  skipped: "не привлекался"
};

export const RISK_TEXT: Record<string, string> = {
  low: "низкий",
  medium: "средний",
  high: "высокий"
};

export const TOOL_TEXT: Record<string, string> = {
  get_quality_margins: "запасы по качеству",
  get_forecast_and_uncertainty: "прогноз и его неопределённость",
  get_tank_projection: "проекцию резервуара",
  get_setpoint_changes: "число изменений уставок",
  get_robustness: "итог проверки устойчивости",
  search_candidates: "поиск кандидатов",
  rank_allowed: "ранжирование допущенных",
  ask_quality_agent: "консультацию качества",
  ask_reliability_agent: "консультацию надёжности",
  finalize: "фиксацию итога",
  submit_opinion: "подачу мнения"
};

export function toolText(name: string | undefined): string | null {
  if (!name) return null;
  return TOOL_TEXT[name] ?? name;
}

export function sameConstraint(a: ProposedConstraint, b: ProposedConstraint): boolean {
  return a.type === b.type
    && (a.limit ?? null) === (b.limit ?? null)
    && (a.value ?? null) === (b.value ?? null);
}

export function constraintDetail(item: ProposedConstraint): string | null {
  const parts: string[] = [];
  if (item.limit) parts.push(item.limit);
  if (typeof item.value === "number") parts.push(String(item.value));
  return parts.length > 0 ? parts.join(" · ") : null;
}

export function constraintLines(opinion: AgentOpinion, applied: ProposedConstraint[]): ConstraintLine[] {
  const proposed = opinion.proposed_constraints ?? [];
  return proposed.map((item, index) => ({
    key: `${item.type}-${index}`,
    label: CONSTRAINT_TEXT[item.type] ?? item.type,
    detail: constraintDetail(item),
    applied: applied.some((other) => sameConstraint(item, other))
  }));
}

export function planChanged(agentic: Agentic): boolean {
  const final = agentic.final;
  if (!final || final.action !== "select") return false;
  const chosen = final.candidate_id;
  if (!chosen) return false;
  const trace = Array.isArray(agentic.trace) ? agentic.trace : [];
  const sawSearch = trace.some((item) => {
    if (!item || typeof item !== "object") return false;
    const name = (item as Record<string, unknown>)["tool_name"];
    return name === "search_candidates" || name === "rank_allowed";
  });
  if (!sawSearch) return false;
  const vetoed = Object.keys(agentic.vetoed_candidates ?? {}).length > 0;
  const constrained = (agentic.constraints_applied ?? []).length > 0;
  return vetoed || constrained;
}

export function skippedText(payload: ScreenPayload | null, agentic: Agentic): string | null {
  if (agentic.outcome !== "skipped") return null;
  const reason = agentic.fallback_reason;
  const kind = payload?.explanation.kind ?? payload?.decision.refusal?.kind ?? null;
  if (reason === "data_refusal" || kind === "bad_data" || kind === "data") {
    return "Агенты не запускались: нет пригодного источника. Расчёт остановлен на проверке доверия "
      + "к данным, поэтому ни одна роль не высказывалась и на итог не влияла.";
  }
  return reason !== null
    ? `Агенты не запускались. Отметка причины: ${reason}.`
    : "Агенты не запускались, причина в результате не отмечена.";
}

export function absentText(payload: ScreenPayload | null): string {
  const kind = payload?.explanation.kind ?? payload?.decision.refusal?.kind ?? null;
  if (kind === "bad_data" || kind === "data") {
    return "Агенты не запускались: нет пригодного источника.";
  }
  return "Агентного слоя в этом результате нет: ролей не вызывали, влияния на итог у них нет.";
}
