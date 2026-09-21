import type { ScreenPayload } from "../types";
import { controlLabel, controlUnit, isNumber, num } from "../format";
import { humanizeReason } from "../run/orchRead";

/**
 * Компактный ответ оператору над подробной схемой (finalization-plan.md, пункт 2):
 * вердикт → что сделать относительно текущего режима → главная причина → обязательное условие
 * или предупреждение. Схема, трасса и JSON остаются ниже, в «Итоге» и по этапам — как доказательства.
 */

// Независимая проверка (2026-09-20): при потере телеметрии карточка писала «допустимый план не
// найден», хотя поиск вообще не запускался (отказ на проверке данных, до Gate/optimizer). Текст
// отказа теперь различает четыре канонических explanation.kind из explain_types.py: bad_data
// (источника нет — поиск не проводился), model_not_applicable (режим вне области модели),
// no_feasible_plan (поиск шёл, ни один план не прошёл проверки) и agent_rejected (план был, но
// агенты отклонили).
const REFUSAL_TEXT: Record<string, string> = {
  bad_data: "Действие не выдано: нет достоверного источника качества, поиск плана не проводился.",
  model_not_applicable: "Действие не выдано: текущий режим вышел за объявленную область применимости модели.",
  no_feasible_plan: "Действие не выдано: поиск планов прошёл, но ни один не прошёл обязательные проверки.",
  agent_rejected: "Действие не выдано: допустимый план был, но агенты качества/надёжности его отклонили."
};

function refusalLine(payload: ScreenPayload): string {
  const kind = payload.explanation.kind;
  return (kind && REFUSAL_TEXT[kind]) ?? "Действие не выдано: расчёт отказал, причина — ниже.";
}

const RECIPE_DIGITS = 3;

interface ControlsLike {
  controls?: Record<string, number>;
  recipe?: Record<string, number>;
  throughput_tph?: number | null;
}

// Независимая проверка (второй заход): decision.current_operation часто отсутствует, а фактический
// текущий режим лежит в explanation.current_operation — тот же приоритет, что StateStage.tsx уже
// использует (`explanation.current_operation ?? decision.current_operation`). changeSummary раньше
// смотрел только decision.current_operation и поэтому падал в null даже когда данные для сравнения
// были прямо в payload.
function changeSummary(payload: ScreenPayload): string | null {
  const action = payload.decision.immediate_action;
  const current: ControlsLike | null = payload.explanation.current_operation ?? payload.decision.current_operation;
  if (!action || !current) return null;
  const names = payload.explanation.component_names ?? {};
  const parts: string[] = [];
  const controlKeys = new Set([...Object.keys(current.controls ?? {}), ...Object.keys(action.controls ?? {})]);
  for (const key of [...controlKeys].sort()) {
    const from = current.controls?.[key];
    const to = action.controls?.[key];
    if (!isNumber(from) || !isNumber(to) || Number(from.toFixed(1)) === Number(to.toFixed(1))) continue;
    parts.push(`${controlLabel(key)}: ${num(from, 1)} → ${num(to, 1)} ${controlUnit(key)}`);
  }
  const recipeKeys = new Set([...Object.keys(current.recipe ?? {}), ...Object.keys(action.recipe ?? {})]);
  for (const key of [...recipeKeys].sort()) {
    const from = current.recipe?.[key];
    const to = action.recipe?.[key];
    if (!isNumber(from) || !isNumber(to) || Number(from.toFixed(RECIPE_DIGITS)) === Number(to.toFixed(RECIPE_DIGITS))) continue;
    parts.push(`доля ${names[key] ?? key}: ${num(from, RECIPE_DIGITS)} → ${num(to, RECIPE_DIGITS)}`);
  }
  if (
    isNumber(current.throughput_tph) && isNumber(action.throughput_tph)
    && Number(current.throughput_tph.toFixed(1)) !== Number(action.throughput_tph.toFixed(1))
  ) {
    parts.push(`Производительность: ${num(current.throughput_tph, 1)} → ${num(action.throughput_tph, 1)} т/ч`);
  }
  if (parts.length === 0) return null;
  return parts.slice(0, 3).join("; ") + (parts.length > 3 ? `; ещё ${parts.length - 3}` : "");
}

function actionLine(payload: ScreenPayload): string {
  const decision = payload.decision;
  if (decision.status === "refuse") return refusalLine(payload);
  if (decision.status === "hold") {
    return "Сохранить текущий режим: изменения уставок не требуются.";
  }
  const summary = changeSummary(payload);
  const changes = decision.selected_plan?.changes;
  const changesText = typeof changes === "number" ? ` (изменений в плане: ${changes})` : "";
  if (summary) return `Изменить: ${summary}${changesText}.`;
  return `Перейти на другой режим${changesText}; конкретные уставки — на этапе «Итог» ниже.`;
}

// Предупреждение о потере допустимости (хрупкий план или неизмеренный резервуар) должно быть
// заметнее идентификатора плана — см. явные формулировки в risk_block.py (_fragile_plan_items,
// _tank_estimate_items), сюда они приходят как explanation.risk.items.
const CRITICAL_RISK_KINDS = new Set(["fragile_plan", "tank_estimate_sensitive"]);

function mandatoryNote(payload: ScreenPayload): { text: string; critical: boolean } | null {
  const items = payload.explanation.risk?.items ?? [];
  const critical = items.find((item) => CRITICAL_RISK_KINDS.has(item.kind));
  if (critical) return { text: critical.text, critical: true };
  const warnings = payload.explanation.warnings ?? [];
  if (warnings.length > 0 && warnings[0]) return { text: warnings[0].text, critical: false };
  const deployment = payload.decision.deployment_readiness;
  if (deployment && !deployment.ready) {
    return {
      text: "Промышленное применение пока заблокировано: заводом не переданы обязательные вводные.",
      critical: false
    };
  }
  return null;
}

export function OperatorAnswer({ payload }: { payload: ScreenPayload }) {
  const refused = payload.decision.status === "refuse";
  const note = mandatoryNote(payload);

  return (
    <section className="answer" aria-labelledby="answer-title">
      <p className={`answer__verdict ${refused ? "answer__verdict--refuse" : ""}`} id="answer-title">
        {payload.status_label}
      </p>
      <p className="answer__action">{actionLine(payload)}</p>
      <p className="answer__reason">{humanizeReason(payload.decision.reason)}</p>
      {note ? (
        <p className={`answer__note ${note.critical ? "answer__note--critical" : ""}`}>{note.text}</p>
      ) : null}
    </section>
  );
}
