export const AGENT_NAMES: Record<string, string> = {
  orchestrator: "оркестратор",
  quality: "агент качества",
  reliability: "агент надёжности",
  system: "детерминированный код"
};

export const KIND_TEXT: Record<string, string> = {
  llm_call: "обращение к модели",
  consult: "консультация специалиста",
  tool: "вызов инструмента",
  final: "ответ агента",
  resolution: "мнение оформлено",
  guard: "перепроверка кодом",
  fallback: "откат на детерминированную политику"
};
