import type { Alternative, ScreenPayload } from "../types";
import { isNumber } from "../format";

export type CompareRole = "selected" | "alternative";

export interface CompareCell {
  text: string;
  known: boolean;
}

export interface CompareRow {
  key: string;
  role: CompareRole;
  id: string;
  action: string;
  hold: boolean;
  production: CompareCell;
  cost: CompareCell;
  severity: CompareCell;
  changes: CompareCell;
  why: string;
}

export interface CompareModel {
  rows: CompareRow[];
  rule: string | null;
  horizonHours: number | null;
  horizonSource: string | null;
  alternativesTotal: number;
  alternativesShown: number;
  paired: boolean;
  blocked: string | null;
  holdNote: string;
}

const CAP = 2;

function cell(value: unknown, digits: number): CompareCell {
  if (!isNumber(value)) return { text: "нет оценки", known: false };
  const rounded = Number(value.toFixed(digits));
  return { text: rounded.toLocaleString("ru-RU", { maximumFractionDigits: digits }), known: true };
}

function planHorizon(payload: ScreenPayload): { hours: number | null; source: string | null } {
  const steps = payload.decision.selected_plan?.steps ?? [];
  const last = steps[steps.length - 1];
  if (steps.length > 1 && last && isNumber(last.time_hours)) {
    return { hours: last.time_hours, source: "decision.selected_plan.steps" };
  }
  const look = payload.decision.lookahead?.lookahead_hours;
  if (isNumber(look)) return { hours: look, source: "decision.lookahead.lookahead_hours" };
  return { hours: null, source: null };
}

function isHoldPlan(payload: ScreenPayload): boolean {
  const plan = payload.decision.selected_plan;
  if (!plan) return false;
  return plan.plan_id === "hold" || payload.decision.status === "hold";
}

function selectedWhy(hold: boolean): string {
  if (hold) {
    return "Выбран как лучший из допустимых по действующему правилу ранжирования: менять режим не потребовалось.";
  }
  return "Выбран как лучший из допустимых по действующему правилу ранжирования, приведённому ниже.";
}

function blockedText(payload: ScreenPayload): string | null {
  if (payload.decision.status !== "refuse") return null;
  const kind = payload.explanation.kind ?? payload.decision.refusal?.kind ?? null;
  if (kind === "agent_rejected") {
    return "Сравнивать нечего: допустимые планы были, но решение не выдано после отклонения агентами "
      + "качества и надёжности. Кто и почему отклонил — в карточках агентов.";
  }
  if (kind === "bad_data" || kind === "data" || kind === "data_refusal") {
    return "Сравнения нет: поиск планов не запускался, потому что ни один источник качества не признан "
      + "пригодным. Нулей здесь не показываем — расчёта не было.";
  }
  if (kind === "no_feasible_plan") {
    return "Сравнения нет: ни один вариант не прошёл обязательные проверки, поэтому предпочитать было "
      + "не из чего. Отклонённые варианты с причинами — на этапе «Кандидаты».";
  }
  return "Решение не выдано, поэтому пары «выбранный план — альтернатива» не существует. "
    + "Причина отказа — в ответе оператору.";
}

export function compareModel(payload: ScreenPayload): CompareModel {
  const blocked = blockedText(payload);
  const rule = payload.explanation.comparison_rule ?? null;
  const horizon = planHorizon(payload);
  const plan = payload.decision.selected_plan;
  const source: Alternative[] = payload.explanation.alternatives ?? [];
  const hold = isHoldPlan(payload);

  const holdNote = hold
    ? "Строка «без действия» и есть выбранный план: система предлагает сохранить текущий режим."
    : "Строки «без действия» нет: план hold на тех же условиях в payload не передан. "
      + "Ближайшие альтернативы — это изменённые планы, а не отказ от действия.";

  if (blocked !== null || !plan) {
    return {
      rows: [], rule, horizonHours: horizon.hours, horizonSource: horizon.source,
      alternativesTotal: source.length, alternativesShown: 0, paired: false,
      blocked: blocked ?? "Выбранного плана в payload нет, сравнивать не с чем.", holdNote
    };
  }

  const rows: CompareRow[] = [{
    key: "selected",
    role: "selected",
    id: plan.plan_id,
    action: hold ? "Сохранить текущий режим" : plan.intent,
    hold,
    production: cell(payload.decision.production_t, 1),
    cost: cell(payload.decision.cost_per_tonne, 4),
    severity: cell(payload.decision.severity_index, 3),
    changes: cell(plan.changes, 0),
    why: selectedWhy(hold)
  }];

  for (const item of source.slice(0, CAP)) {
    rows.push({
      key: item.candidate_id,
      role: "alternative",
      id: item.candidate_id,
      action: "Изменённый план",
      hold: false,
      production: cell(item.production_t, 1),
      cost: cell(item.cost_per_tonne, 4),
      severity: cell(item.severity_index, 3),
      changes: cell(item.changes, 0),
      why: item.why_not
    });
  }

  return {
    rows, rule, horizonHours: horizon.hours, horizonSource: horizon.source,
    alternativesTotal: source.length, alternativesShown: rows.length - 1,
    paired: rows.length > 1, blocked: null, holdNote
  };
}
