import type { ScreenPayload } from "../types";
import { isNumber, num } from "../format";

export interface SummaryLine {
  label: string;
  value: string;
  tone: "pass" | "fail" | "unknown" | "idle";
}

export interface SourceLine {
  name: string;
  usable: boolean;
  age: string;
}

export function keyNumbers(payload: ScreenPayload | null): SummaryLine[] {
  if (!payload) return [];
  const decision = payload.decision;
  const gate = decision.gate?.checks ?? [];
  const failed = gate.filter((check) => check.status === "fail").length;
  const unknown = gate.filter((check) => check.status === "unknown").length;
  const out: SummaryLine[] = [
    {
      label: "Вердикт",
      value: payload.status_label,
      tone: decision.status === "refuse" ? "fail" : "pass"
    }
  ];
  if (isNumber(decision.production_t)) {
    out.push({ label: "Выпуск", value: `${num(decision.production_t, 1)} т`, tone: "idle" });
  }
  if (isNumber(decision.cost_per_tonne)) {
    out.push({ label: "Стоимость", value: `${num(decision.cost_per_tonne, 2)} /т`, tone: "idle" });
  }
  if (isNumber(decision.severity_index)) {
    out.push({ label: "Тяжесть режима", value: num(decision.severity_index, 3), tone: "idle" });
  }
  if (gate.length > 0) {
    out.push({
      label: "Нарушения Gate",
      value: failed === 0 && unknown === 0 ? `нет, проверок ${gate.length}` : `${failed} нарушено, ${unknown} неизвестно`,
      tone: failed > 0 ? "fail" : unknown > 0 ? "unknown" : "pass"
    });
  }
  const warnings = payload.explanation.warnings?.length ?? 0;
  if (warnings > 0) {
    out.push({ label: "Предупреждения", value: String(warnings), tone: "unknown" });
  }
  return out;
}

export function sourceLines(payload: ScreenPayload | null): SourceLine[] {
  if (!payload) return [];
  return (payload.sources ?? []).map((source) => ({
    name: source.name,
    usable: source.usable,
    age: isNumber(source.age_hours) ? `${num(source.age_hours, 1)} ч` : "возраст не передан"
  }));
}

export function agentCounters(payload: ScreenPayload | null): SummaryLine[] {
  if (!payload) return [];
  const trace = payload.decision.trace ?? [];
  if (trace.length === 0) return [];
  const vetoes = trace.reduce(
    (acc, event) => acc + ((event["vetoes"] as unknown[] | undefined)?.length ?? 0),
    0
  );
  const agentic = payload.decision.agentic;
  const provider =
    agentic === null || agentic === undefined
      ? "режим не передавался"
      : agentic.mode === "scripted"
        ? "детерминированная политика, не LLM"
        : agentic.outcome === "ok"
          ? `живая модель: ${agentic.model ?? "имя не передано"}`
          : "откат на детерминированный путь";
  return [
    { label: "Участников", value: String(trace.length), tone: "idle" },
    { label: "Вето", value: String(vetoes), tone: vetoes > 0 ? "fail" : "pass" },
    {
      label: "Провайдер",
      value: provider,
      tone: agentic?.mode === "scripted" ? "unknown" : agentic?.outcome === "ok" ? "pass" : "unknown"
    }
  ];
}
