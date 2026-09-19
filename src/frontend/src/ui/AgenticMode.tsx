import type { Agentic } from "../types";
import { Empty, Field, Fields, Note } from "./Primitives";

const OUTCOMES: Record<string, string> = {
  ok: "живая модель отработала",
  fallback: "живая модель не работала, решение принял детерминированный код",
  disabled: "агентный режим выключен"
};

const MODES: Record<string, string> = {
  agentic: "агентный режим",
  scripted: "детерминированная политика, не LLM",
  off: "агентный режим выключен"
};

function toneOf(agentic: Agentic): "live" | "fallback" | "scripted" {
  if (agentic.mode === "scripted") return "scripted";
  return agentic.outcome === "ok" ? "live" : "fallback";
}

function headline(agentic: Agentic): string {
  const tone = toneOf(agentic);
  if (tone === "live") return "Решение принято с участием живой модели";
  if (tone === "scripted") return "Живая модель не участвовала: детерминированная политика, не LLM";
  return "Живая модель не участвовала: сработал запасной детерминированный путь";
}

export function AgenticMode({ agentic }: { agentic: Agentic | null }) {
  if (!agentic) {
    return (
      <Empty>
        Режим работы агентов не передавался: по этому экрану нельзя сказать, работала ли живая модель.
      </Empty>
    );
  }

  const tone = toneOf(agentic);

  return (
    <div className={`mode mode--${tone}`}>
      <p className="mode__headline">{headline(agentic)}</p>
      <Fields>
        <Field label="Режим">{MODES[agentic.mode] ?? agentic.mode}</Field>
        <Field label="Исход">{OUTCOMES[agentic.outcome] ?? agentic.outcome}</Field>
        <Field label="Провайдер">{agentic.provider ?? "не задан"}</Field>
        <Field label="Модель">{agentic.model ?? "не задана"}</Field>
        <Field label="Причина отката">
          {agentic.fallback_reason ? <code>{agentic.fallback_reason}</code> : "отката не было"}
        </Field>
        <Field label="Статус детерминированного пути">{agentic.legacy_status ?? "—"}</Field>
      </Fields>
      {agentic.note ? <Note>{agentic.note}</Note> : null}
    </div>
  );
}
