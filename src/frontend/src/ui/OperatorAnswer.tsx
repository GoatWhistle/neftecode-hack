import type { ScreenPayload } from "../types";

/**
 * Компактный ответ оператору над подробной схемой (finalization-plan.md, пункт 2):
 * вердикт → что сделать относительно текущего режима → главная причина → обязательное условие
 * или предупреждение. Схема, трасса и JSON остаются ниже, в «Итоге» и по этапам — как доказательства.
 */

function actionLine(payload: ScreenPayload): string {
  const decision = payload.decision;
  if (decision.status === "refuse") {
    return "Действие не выдано: без него допустимый план не найден, менять режим сейчас нельзя.";
  }
  if (decision.status === "hold") {
    return "Сохранить текущий режим: изменения уставок не требуются.";
  }
  const changes = decision.selected_plan?.changes;
  const suffix = typeof changes === "number"
    ? ` (изменений в плане: ${changes})`
    : "";
  return `Перейти на другой режим, действие — на этапе «Итог» ниже${suffix}.`;
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
      <p className="answer__kicker">Ответ оператору</p>
      <p className={`answer__verdict ${refused ? "answer__verdict--refuse" : ""}`} id="answer-title">
        {payload.status_label}
      </p>
      <p className="answer__action">{actionLine(payload)}</p>
      <p className="answer__reason">{payload.decision.reason}</p>
      {note ? (
        <p className={`answer__note ${note.critical ? "answer__note--critical" : ""}`}>{note.text}</p>
      ) : null}
    </section>
  );
}
