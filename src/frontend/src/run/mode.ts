import type { RunState } from "./types";

export type ModeKind = "live" | "offline" | "replay" | "pending" | "waiting";

export interface ModeLine {
  kind: ModeKind;
  text: string;
  detail: string | null;
}

function providerText(provider: string | null, model: string | null): string {
  const name = provider ?? "провайдер не назван";
  return model ? `${name} / ${model}` : name;
}

export function modeOf(run: RunState): ModeLine | null {
  if (run.status === "idle") return null;
  if (!run.live) {
    return {
      kind: "replay",
      text: "Запись прогона",
      detail: "повтор записанной трассы, паузы сжаты; сервер не опрашивается"
    };
  }
  const agentic = run.payload?.decision.agentic ?? null;
  if (agentic === null) {
    if (run.payload?.agentic_state) {
      return { kind: "offline", text: "Агенты выключены", detail: run.payload.agentic_state.note };
    }
    return run.status === "running"
      ? { kind: "waiting", text: "Режим уточняется при запуске", detail: null }
      : { kind: "pending", text: "Режим не передан", detail: "сервер не прислал метаданные агентного режима" };
  }
  if (agentic.deterministic_policy === true) {
    return {
      kind: "offline",
      text: "Офлайн-агенты",
      detail: agentic.provider_label ?? "шаги заданы кодом, не рассуждение модели"
    };
  }
  return {
    kind: "live",
    text: `Внешняя LLM: ${providerText(agentic.provider ?? null, agentic.model ?? null)}`,
    detail: null
  };
}
