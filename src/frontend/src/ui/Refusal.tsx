import type { NextStep, OptimizerRound, ScreenPayload, TraceEvent } from "../types";
import { hours, isNumber, num } from "../format";
import { Empty, Field, Fields, Note, Readout, Tag } from "./Primitives";

const KIND_TEXT: Record<string, string> = {
  no_feasible_plan: "Допустимого плана нет: ни один построенный вариант не проходит все обязательные проверки",
  bad_data: "Данные непригодны: достоверного источника качества на момент решения нет",
  data: "Данные непригодны: достоверного источника качества на момент решения нет"
};

const STEP_KIND_TEXT: Record<string, string> = {
  measurement: "измерение",
  resource_or_scenario_condition: "условие сценария или ресурс"
};

interface OptimizerTrace extends TraceEvent {
  rounds?: OptimizerRound[];
  evaluated?: number;
}

function optimizerOf(trace: TraceEvent[]): OptimizerTrace | null {
  const event = trace.find((item) => item.agent === "optimizer");
  return event ? (event as OptimizerTrace) : null;
}

function familyTotals(rounds: OptimizerRound[]): [string, number][] {
  const totals = new Map<string, number>();
  for (const round of rounds) {
    for (const [family, count] of Object.entries(round.veto_families ?? {})) {
      totals.set(family, (totals.get(family) ?? 0) + count);
    }
  }
  return [...totals.entries()].sort((a, b) => b[1] - a[1]);
}

export interface RefusalPanelProps {
  payload: ScreenPayload;
}

export function RefusalPanel({ payload }: RefusalPanelProps) {
  const decision = payload.decision;
  const explanation = payload.explanation;
  const kind = explanation.kind ?? decision.refusal?.kind ?? null;
  const steps: NextStep[] = explanation.next_steps ?? [];
  const missing = decision.refusal?.missing ?? [];
  const examples = decision.refusal?.examples ?? [];
  const optimizer = optimizerOf(decision.trace ?? []);
  const rounds = optimizer?.rounds ?? [];
  const families = familyTotals(rounds);
  const measurements = steps.filter((step) => step.kind === "measurement");

  return (
    <div className="refusal">
      <Fields>
        <Field label="Вид отказа">
          <code>{kind ?? "—"}</code>
        </Field>
        <Field label="Что это означает">{kind ? KIND_TEXT[kind] ?? decision.reason : decision.reason}</Field>
        <Field label="Товарный выпуск разрешён">{decision.commercial_release_allowed ? "да" : "нет"}</Field>
        <Field label="Режим установки">остаётся прежним: советчик ничего не меняет</Field>
      </Fields>

      {rounds.length > 0 ? (
        <>
          <div className="readouts">
            <Readout
              label="Планов проверено"
              value={num(optimizer?.evaluated, 0)}
              hint="ни один не прошёл"
              tone="fail"
            />
            <Readout label="Раундов поиска" value={String(rounds.length)} hint="с ужесточением запретов" />
            <Readout
              label="Допустимых"
              value="0"
              tone="fail"
              hint="планов, прошедших все проверки"
            />
          </div>

          <table className="grid grid--tight">
            <caption>Что именно не сошлось: суммарные вето по семействам ограничений</caption>
            <thead>
              <tr>
                <th scope="col">Семейство ограничений</th>
                <th scope="col">Вето за все раунды</th>
              </tr>
            </thead>
            <tbody>
              {families.map(([family, count]) => (
                <tr key={family}>
                  <th scope="row">{family}</th>
                  <td className="grid__num">{num(count, 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <Note>
            Семейство с наибольшим числом вето — то, из-за которого совет невозможен. Числа в этой таблице
            считают отклонённые проверки внутри перебора, а не измерения установки.
          </Note>
        </>
      ) : null}

      {missing.length > 0 ? (
        <div className="limits">
          <p className="limits__head">Чего не хватило по данным</p>
          <ul className="limits__list">
            {missing.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {steps.length > 0 ? (
        <table className="grid">
          <caption>Что изменило бы ответ</caption>
          <thead>
            <tr>
              <th scope="col">Условие или измерение</th>
              <th scope="col">Тип</th>
              <th scope="col">Когда будет</th>
            </tr>
          </thead>
          <tbody>
            {steps.map((step, position) => (
              <tr key={`${step.need}-${position}`}>
                <td>
                  {step.need}
                  {step.caveat ? <span className="refusal__caveat">{step.caveat}</span> : null}
                </td>
                <td>
                  <Tag tone="unknown">{STEP_KIND_TEXT[step.kind] ?? step.kind}</Tag>
                </td>
                <td className="grid__num">
                  {isNumber(step.available_in_hours) ? `до ${hours(step.available_in_hours)}` : "срок не передавался"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <Empty>Список недостающих условий не передавался.</Empty>
      )}

      {examples.length > 0 ? (
        <Note tone="warn">
          Строки выше — примеры нарушений внутри перебора планов: это расчётные исходы проверенных вариантов,
          а не измерения установки. Ни одно из чисел в них не снято с приборов.
        </Note>
      ) : null}

      {measurements.length > 0 ? (
        <Note tone="warn">
          Пока перечисленные измерения не получены, любой совет опирался бы на непроверенное значение. Отказ
          снимается измерением, а не ослаблением предела.
        </Note>
      ) : null}
    </div>
  );
}
