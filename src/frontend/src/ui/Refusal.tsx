import type { NextStep, OptimizerRound, ScreenPayload, TraceEvent } from "../types";
import { hours, isNumber, num } from "../format";
import { humanizeReason } from "../run/orchRead";
import { Empty, Field, Fields, Note, Readout, Tag } from "./Primitives";
import { VetoFunnel } from "./VetoFunnel";

const KIND_TEXT: Record<string, string> = {
  no_feasible_plan: "Допустимого плана нет: ни один построенный вариант не проходит все обязательные проверки",
  bad_data: "Данные непригодны: достоверного источника качества на момент решения нет",
  data: "Данные непригодны: достоверного источника качества на момент решения нет",
  agent_rejected: "Допустимый план был, но агенты качества/надёжности его отклонили: решение не выдаётся",
  tank_phase_sensitive: "Общий план для всех фаз парка не подтверждён: нужен фактический уровень резервуаров"
};

const STEP_KIND_TEXT: Record<string, string> = {
  measurement: "измерение",
  resource_or_scenario_condition: "условие сценария или ресурс",
  agent_review: "решение агентов"
};

interface OptimizerTrace extends TraceEvent {
  rounds?: OptimizerRound[];
  evaluated?: number;
}

function optimizerOf(trace: TraceEvent[]): OptimizerTrace | null {
  const event = trace.find((item) => item.agent === "optimizer");
  return event ? (event as OptimizerTrace) : null;
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
  const measurements = steps.filter((step) => step.kind === "measurement");
  const zeroFeasible = kind === "no_feasible_plan";
  const phaseSensitive = kind === "tank_phase_sensitive";
  const feasibleCount = zeroFeasible ? 0 : (rounds.length > 0 ? (rounds[rounds.length - 1]?.feasible ?? 0) : 0);

  return (
    <div className="refusal">
      <Fields>
        <Field label="Вид отказа">
          <code>{kind ?? "—"}</code>
        </Field>
        <Field label="Что это означает">
          {kind ? KIND_TEXT[kind] ?? humanizeReason(decision.reason) : humanizeReason(decision.reason)}
        </Field>
        <Field label="Товарный выпуск разрешён">{decision.commercial_release_allowed ? "да" : "нет"}</Field>
        <Field label="Режим установки">остаётся прежним: советчик ничего не меняет</Field>
      </Fields>

      {rounds.length > 0 ? (
        <>
          <div className="readouts">
            <Readout
              label="Планов проверено"
              value={num(optimizer?.evaluated, 0)}
              hint={zeroFeasible ? "ни один не прошёл" : (phaseSensitive ? "общий план для всех фаз не подтверждён" : "часть прошла проверки, но не устроила агентов")}
              tone={zeroFeasible || phaseSensitive ? "fail" : "unknown"}
            />
            <Readout label="Раундов поиска" value={String(rounds.length)} hint="с ужесточением запретов" />
            <Readout
              label="Допустимых"
              value={String(feasibleCount)}
              tone={zeroFeasible || phaseSensitive ? "fail" : "unknown"}
              hint={zeroFeasible ? "планов, прошедших все проверки" : (phaseSensitive ? "прошли номинальную проверку, но не подтверждены на всём интервале фаз" : "прошли обязательные проверки; лучший отклонён агентами")}
            />
          </div>

          <VetoFunnel rounds={rounds} compact />
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
