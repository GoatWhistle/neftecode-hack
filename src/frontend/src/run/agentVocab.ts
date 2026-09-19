export const CONSTRAINT_VOCABULARY = [
  "min_quality_margin",
  "max_changes",
  "forbid_additive",
  "max_outflow_utilization",
  "constant_plans_only",
  "min_hours_to_violation",
  "require_not_fragile"
] as const;

export const CONSTRAINT_TEXT: Record<string, string> = {
  min_quality_margin: "запас по качеству",
  max_changes: "предел числа переключений",
  forbid_additive: "запрет присадки",
  max_outflow_utilization: "потолок загрузки отбора",
  constant_plans_only: "только постоянные планы",
  min_hours_to_violation: "часы до нарушения",
  require_not_fragile: "требовать нехрупкий план"
};

export const RESOLUTION_TEXT: Record<string, string> = {
  rank_overrides_choice: "код выбрал другой план, чем назвал оркестратор",
  legacy_excluded: "план базового расчёта исключён агентами",
  selection_not_allowed: "названный план вне списка допущенных",
  refuse_ignored: "отказ отклонён: ни одно мнение его не подтвердило",
  extra_tool_calls_dropped: "лишние вызовы инструментов отброшены"
};

export const FINISH_TEXT: Record<string, string> = {
  tool_calls: "модель сама вызвала инструмент",
  stop: "модель договорила",
  length: "модель упёрлась в предел длины ответа",
  content_filter: "ответ обрезан фильтром провайдера"
};

export function resolutionText(decision: string | undefined | null): string {
  if (!decision) return "решение без пометки";
  return RESOLUTION_TEXT[decision] ?? decision;
}

export function finishText(decision: string | undefined | null): string {
  if (!decision) return "причина остановки не передана провайдером";
  return FINISH_TEXT[decision] ?? decision;
}
