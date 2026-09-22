import type { Agentic, Choice, ChoiceCard, ChoiceReason } from "../../types";

export const VERDICT_TEXT: Record<ChoiceCard["verdict"], string> = {
  selected: "выбран",
  admissible_not_selected: "допустим, но не выбран политикой",
  excluded: "исключён"
};

export const CATEGORY_TEXT: Record<string, string> = {
  gate_fail: "нарушен базовый Gate",
  gate_unknown: "проверка UNKNOWN",
  policy_not_selected: "не выбран политикой",
  policy_limit: "снят пределом политики",
  lookahead: "упреждение за горизонтом",
  final_veto: "финальная проверка не пройдена",
  agent_veto: "вето агента",
  agent_constraint: "ограничение агента",
  not_in_final_pool: "вне финального пула"
};

export const STAGE_TEXT: Record<string, string> = {
  ranking: "правило ранжирования",
  policy: "политика выбора",
  lookahead: "упреждение за горизонтом",
  final_veto: "финальная проверка",
  agents: "агентный этап",
  data: "данные",
  search: "поиск и Gate",
  final_recheck: "финальная перепроверка",
  unknown: "не определён"
};

export interface ChoiceColumns {
  hold: ChoiceCard | null;
  selected: ChoiceCard | null;
  cheaper: ChoiceCard | null;
  others: ChoiceCard[];
}

export function columnsOf(choice: Choice): ChoiceColumns {
  const byId = new Map(choice.candidates.map((card) => [card.candidate_id, card]));
  const pick = (id: string | null) => (id !== null ? byId.get(id) ?? null : null);
  const selected = pick(choice.selected_id);
  const hold = choice.hold_id === choice.selected_id ? null : pick(choice.hold_id);
  const cheaper = pick(choice.cheaper_id);
  const shown = new Set([selected, hold, cheaper].filter(Boolean).map((card) => card!.candidate_id));
  return { hold, selected, cheaper, others: choice.candidates.filter((card) => !shown.has(card.candidate_id)) };
}

/** Агентный этап не завершился штатно: это не предметная невозможность, если расчёт её не доказал. */
export function agentStopNote(agentic: Agentic | null | undefined): string | null {
  if (!agentic || agentic.outcome !== "fallback") return null;
  const reason = agentic.fallback_reason ?? "причина не передана";
  return `Агентный этап не завершён штатно (${reason}). Итог выдан детерминированным ядром; `
    + "это не доказательство того, что допустимого решения нет.";
}

export function reasonKey(card: ChoiceCard, reason: ChoiceReason, index: number): string {
  return `${card.candidate_id}:${reason.category}:${index}`;
}
