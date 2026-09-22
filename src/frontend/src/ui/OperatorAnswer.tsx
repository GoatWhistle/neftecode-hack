import type { ScreenPayload } from "../types";
import { changeLines, changeText } from "../run/changes";
import { humanizeReason } from "../run/orchRead";
import { checkFamilies } from "../run/checks";
import type { RunOutcome } from "../run/verdict";
import { seriousRiskItems, verdictOf } from "../run/verdict";
import { num } from "../format";

/**
 * Компактный ответ оператору над подробной схемой (finalization-plan.md, пункт 2):
 */


function changeSummary(payload: ScreenPayload): string | null {
  const lines = changeLines(payload);
  if (lines === null || lines.length === 0) return null;
  return lines.map(changeText).join("; ");
}

function actionLine(payload: ScreenPayload): string {
  const decision = payload.decision;
  if (decision.status === "refuse") return "Советчик не выдал рекомендацию: допустимость режима не подтверждена.";
  if (decision.status === "hold") return "Изменения не требуются: текущий режим сохраняется.";
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
      {result && result.decision.status !== "refuse" ? <p className="answer__action">{actionLine(result)}</p> : null}
      {result ? <p className="answer__reason">{humanizeReason(result.decision.reason)}</p> : null}
      {verdict.lines.filter((line) => !(result?.decision.reason && line.kind === "cause")).map((line) => (
        <p key={`${line.kind}:${line.text}`} className={`answer__line answer__line--${line.kind}`}>
          {line.text}
        </p>
      ))}
      {result?.decision.selected_plan ? <dl className="answer__metrics">
        <div><dt>Выпуск за горизонт</dt><dd>{num(result.decision.production_t, 1)} т</dd></div>
        <div><dt>Условная стоимость</dt><dd>{num(result.decision.cost_per_tonne, 3)} у.е./т</dd></div>
        <div><dt>Тяжесть режима</dt><dd>{num(result.decision.severity_index, 3)}</dd></div>
      </dl> : null}
      {result && result.decision.status !== "refuse" ? <RiskList payload={result} /> : null}
      {result ? <p className="answer__scope">{result.decision.commercial_release_allowed
        ? "Допуск товарного выпуска указан в полном протоколе."
        : "Результат расчёта не разрешает товарный выпуск."}</p> : null}
      {result ? <details className="answer__details">
        <summary>Проверки и границы применимости</summary>
        {result.decision.status === "refuse" ? <RiskList payload={result} /> : null}
        <CheckStrip payload={result} />
      {verdict.backendStatus ? (
        <p className="answer__audit">
          Статус backend для аудита: <code>{verdict.backendStatus}</code>
          {verdict.backendLabel ? ` · «${verdict.backendLabel}»` : ""}
        </p>
      ) : null}
      </details> : null}
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
