import type { Agentic } from "../types";
import { Empty, Field, Fields, Note } from "./Primitives";

// Реальные значения agentic.outcome (AgenticMakeDecision._with в decision.py):
// "selected" — агенты выбрали план; "confirmed_legacy" — агенты подтвердили детерминированный план;
// "refused" — агенты дошли до вердикта и отказали; "fallback" — настоящий сбой (провайдер не
// настроен/упал, veto без основания и т.п.); "skipped" — до агентов не дошло (отказ на проверке
// данных). Значения "ok"/"disabled" в backend не существуют и здесь остаются только для обратной
// совместимости со старыми записанными трассами.
const OUTCOMES: Record<string, string> = {
  ok: "живая модель отработала",
  selected: "агенты выбрали план",
  confirmed_legacy: "агенты подтвердили детерминированный план",
  refused: "агенты дошли до отказа",
  fallback: "живая модель не работала, решение принял детерминированный код",
  disabled: "агентный режим выключен",
  skipped: "агенты не привлекались: отказ произошёл раньше, на проверке данных"
};

const MODES: Record<string, string> = {
  agentic: "агентный режим",
  scripted: "детерминированная политика, не LLM",
  off: "агентный режим выключен"
};

// legacy_status — код итога детерминированного ядра (domain/shared/primitives.py: HOLD, RECOMMEND_SCENARIO,
// REFUSE). Человеческая подпись здесь, код — в JSON ниже по странице.
const LEGACY_STATUS: Record<string, string> = {
  hold: "сохранить режим",
  recommend_scenario: "изменить режим",
  refuse: "отказ"
};

const REAL_FALLBACK_OUTCOMES = new Set(["fallback"]);

// Backend всегда шлёт agentic.mode = "agentic" (см. AgenticMakeDecision.decide) — mode никогда не
// становится "scripted", реальный признак детерминированного пути — отдельный флаг
// deterministic_policy. И backend никогда не шлёт outcome "ok": настоящие значения после успешного
// прогона — "selected"/"confirmed_legacy"/"refused". Раньше тон читался как
// `outcome === "ok" ? "live" : "fallback"`, поэтому КАЖДЫЙ обычный завершённый прогон (agentic.outcome
// всегда "selected"/"confirmed_legacy"/"refused", никогда "ok") подписывался «сработал запасной
// детерминированный путь», хотя Причина отката оставалась пустой («отката не было») — та самая
// противоречивая пара из finalization-plan.md.
function toneOf(agentic: Agentic): "live" | "fallback" | "scripted" | "off" | "skipped" {
  if (agentic.outcome === "skipped") return "skipped";
  if (agentic.outcome === "disabled") return "off";
  if (REAL_FALLBACK_OUTCOMES.has(agentic.outcome)) return "fallback";
  if (agentic.deterministic_policy || agentic.mode === "scripted") return "scripted";
  return "live";
}

function headline(agentic: Agentic): string {
  const tone = toneOf(agentic);
  if (tone === "live") return "Решение принято с участием живой модели";
  if (tone === "scripted") return "Живая модель не участвовала: детерминированная политика, не LLM";
  if (tone === "off") return "Агентный режим выключен: решение принял детерминированный код без участия LLM";
  if (tone === "skipped") return "Агенты не привлекались: отказ случился раньше, на проверке данных";
  return "Живая модель не участвовала: сработал запасной детерминированный путь после сбоя провайдера";
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
        <Field label="Статус детерминированного пути">
          {agentic.legacy_status
            ? (LEGACY_STATUS[agentic.legacy_status] ?? agentic.legacy_status)
            : "—"}
        </Field>
      </Fields>
      {agentic.note ? <Note>{agentic.note}</Note> : null}
    </div>
  );
}
