import type { ScreenPayload } from "../types";
import { controlLabel, controlUnit, isNumber, num } from "../format";
import { humanizeReason } from "../run/orchRead";
import { checkFamilies } from "../run/checks";
import type { RunOutcome } from "../run/verdict";
import { seriousRiskItems, verdictOf } from "../run/verdict";

/**
 * Компактный ответ оператору над подробной схемой (finalization-plan.md, пункт 2):
 */

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
  if (decision.status === "refuse") return "Уставки не менять: выдавать нечего.";
  if (decision.status === "hold") return "Сохранить текущий режим: изменения уставок не требуются.";
  const summary = changeSummary(payload);
  const changes = decision.selected_plan?.changes;
  const changesText = typeof changes === "number" ? ` (изменений в плане: ${changes})` : "";
  if (summary) return `Изменить: ${summary}${changesText}.`;
  return `Перейти на другой режим${changesText}; конкретные уставки — на этапе «Итог» ниже.`;
}

export interface OperatorAnswerProps {
  payload?: ScreenPayload | null;
  outcome?: RunOutcome;
}

export function OperatorAnswer({ payload, outcome }: OperatorAnswerProps) {
  const resolved: RunOutcome | null = outcome ?? (payload ? { kind: "result", payload } : null);
  if (!resolved) return null;
  const verdict = verdictOf(resolved);
  const result = resolved.kind === "result" ? resolved.payload : null;

  return (
    <section className={`answer answer--${verdict.tone}`} aria-labelledby="answer-title">
      <p className={`answer__verdict answer__verdict--${verdict.tone}`} id="answer-title">
        {verdict.title}
      </p>
      {verdict.qualifier ? <p className="answer__qualifier">{verdict.qualifier}</p> : null}
      {result ? <p className="answer__action">{actionLine(result)}</p> : null}
      {result ? <p className="answer__reason">{humanizeReason(result.decision.reason)}</p> : null}
      {verdict.lines.map((line) => (
        <p key={`${line.kind}:${line.text}`} className={`answer__line answer__line--${line.kind}`}>
          {line.text}
        </p>
      ))}
      {result ? <RiskList payload={result} /> : null}
      {result ? <CheckStrip payload={result} /> : null}
      {verdict.backendStatus ? (
        <p className="answer__audit">
          Статус backend для аудита: <code>{verdict.backendStatus}</code>
          {verdict.backendLabel ? ` · «${verdict.backendLabel}»` : ""}
        </p>
      ) : null}
    </section>
  );
}

function RiskList({ payload }: { payload: ScreenPayload }) {
  const items = seriousRiskItems(payload);
  const warnings = (payload.explanation.warnings ?? []).filter(
    (warning) => !items.some((item) => item.kind === warning.kind)
  );
  if (items.length === 0 && warnings.length === 0) return null;
  return (
    <ul className="answer__risks">
      {items.map((item) => (
        <li key={item.kind} className={`answer__risk answer__risk--${item.level}`}>
          {item.text}
        </li>
      ))}
      {warnings.map((warning) => (
        <li key={`w:${warning.kind}`} className="answer__risk answer__risk--low">
          {warning.text}
        </li>
      ))}
    </ul>
  );
}

function CheckStrip({ payload }: { payload: ScreenPayload }) {
  return (
    <dl className="answer__checks">
      {checkFamilies(payload).map((family) => (
        <div key={family.id} className={`answer__check answer__check--${family.tone}`}>
          <dt className="answer__check-title">{family.title}</dt>
          <dd className="answer__check-value">{family.value}</dd>
          <dd className="answer__check-detail">{family.detail}</dd>
        </div>
      ))}
    </dl>
  );
}
