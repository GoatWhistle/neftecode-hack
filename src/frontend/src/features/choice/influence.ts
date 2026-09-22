import type { Choice } from "../../types";
import type { InfluenceRef } from "../evidence-passport/model";
import { constraintKey } from "../evidence-passport/model";

/**
 * Связи «ограничение агента → итог» для паспорта P3: только когда трасса choice доказывает,
 * что выбор ядра исключён именно этим ограничением. Иначе ссылки нет — паспорт пишет
 * «влияние на выбор не установлено».
 */
export function influenceRefsOf(choice: Choice | null | undefined): Record<string, InfluenceRef> {
  const refs: Record<string, InfluenceRef> = {};
  const agents = choice?.agents;
  if (!choice || !agents?.legacy_excluded || !agents.legacy_plan_id) return refs;
  const legacy = choice.candidates.find((card) => card.candidate_id === agents.legacy_plan_id);
  for (const reason of legacy?.reasons ?? []) {
    if (reason.category !== "agent_constraint" || reason.rule?.id !== "agent_constraint") continue;
    const constraints = (reason.rule.constraints as { type: string; limit?: string | null; value?: number | null }[]) ?? [];
    for (const item of constraints) {
      refs[constraintKey({ type: item.type, ...(item.limit ? { limit: item.limit } : {}),
        ...(typeof item.value === "number" ? { value: item.value } : {}) })] = {
        text: `исключило план ядра ${agents.legacy_plan_id}; выбран ${choice.selected_id ?? "отказ"}`,
        href: "#chc-title"
      };
    }
  }
  return refs;
}
