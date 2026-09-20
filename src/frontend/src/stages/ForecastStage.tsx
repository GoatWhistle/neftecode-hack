import type { GateCheck, Statement } from "../types";
import { hours, isNumber, num } from "../format";
import { Empty, Field, Fields, Note, Readout } from "../ui/Primitives";
import { OriginBadge } from "../ui/Origin";
import { Section } from "../ui/Section";
import { JsonPanel } from "../ui/Json";
import { MarginBars, buildRows } from "../ui/MarginBars";
import { Trajectory } from "../ui/Trajectory";
import type { StageProps } from "./StateStage";

const TRACKED = "quality.sulfur_mgkg";

function series(checks: GateCheck[]): GateCheck[] {
  return checks
    .filter((check) => check.constraint_id === TRACKED && isNumber(check.observed) && isNumber(check.time_hours))
    .sort((a, b) => (a.time_hours ?? 0) - (b.time_hours ?? 0));
}

function sulfurStatement(statements: Statement[]): Statement | undefined {
  return statements.find((item) => item.topic === "sulfur_mgkg");
}

export function ForecastStage({ payload, index, state, source, lamp, lampTitle, bare }: StageProps) {
  const checks = payload.decision.gate?.checks ?? [];
  const points = series(checks);
  const limit = points.find((check) => isNumber(check.limit))?.limit ?? null;
  const worst = points.reduce<GateCheck | null>(
    (acc, check) => (acc === null || (check.observed ?? 0) > (acc.observed ?? 0) ? check : acc),
    null
  );
  const margin = isNumber(limit) && worst && isNumber(worst.observed) ? limit - worst.observed : null;
  const statements = payload.explanation.statements ?? [];
  const statement = sulfurStatement(statements);
  const marginRows = buildRows(statements);

  return (
    <Section
      id="forecast"
      index={index}
      state={state}
      source={source}
      title="Прогноз"
      lead="Запасы по всем нормируемым свойствам продукта и траектория серы по горизонту плана."
      lamp={lamp}
      lampTitle={lampTitle}
      bare={bare}
    >
      {payload.forecast === null ? (
        <Empty>
          Отдельного блока прогноза с интервалом неопределённости в этом решении нет: поле{" "}
          <code>forecast</code> пустое, и подставлять сюда интервал было бы выдумкой. Ниже — расчётная
          траектория серы, которую проверял Gate: это точки плана, а не измерения.
        </Empty>
      ) : null}

      {marginRows.length > 0 ? (
        <MarginBars statements={statements} />
      ) : (
        <Empty>
          Утверждений о свойствах качества в payload не передавалось, поэтому запасы по пределам
          показать не из чего. Пустой блок означает отсутствие утверждений, а не отсутствие рисков.
        </Empty>
      )}

      {points.length === 0 ? (
        payload.decision.status === "refuse" ? (
          <Empty>
            Траектории серы здесь нет: её строят по проверкам выбранного плана, а плана нет. Пустой график
            означает отсутствие расчёта, а не благополучие по сере — уровень серы остаётся тем же, из-за
            которого план не нашёлся.
          </Empty>
        ) : (
          <Empty>Точек по сере в проверках нет.</Empty>
        )
      ) : (
        <>
          <div className="readouts">
            <Readout
              label="Худшая точка по сере"
              value={num(worst?.observed, 3)}
              unit="мг/кг"
              tone={margin !== null && margin > 0 ? "pass" : "fail"}
              hint={worst ? `на ${hours(worst.time_hours)}` : undefined}
              badge={<OriginBadge origin="derived" />}
            />
            <Readout
              label="Предел"
              value={num(limit, 2)}
              unit="мг/кг"
              hint="требование к товарному дизелю"
              badge={<OriginBadge origin="given" />}
            />
            <Readout
              label="Запас до предела"
              value={num(margin, 3)}
              unit="мг/кг"
              tone={margin !== null && margin >= 1 ? "pass" : "unknown"}
              hint="технологический запас на установке — 1 мг/кг"
              badge={<OriginBadge origin="derived" />}
            />
            <Readout label="Точек на горизонте" value={String(points.length)} hint="шагов проверки" />
          </div>

          <Trajectory
            points={points.map((check) => ({
              time: check.time_hours ?? 0,
              value: check.observed ?? 0
            }))}
            limit={limit}
            unit="мг/кг"
            label="Сера в товарном дизеле по времени"
            digits={3}
          />

          {statement ? (
            <Fields>
              <Field label="Утверждение о сере">{statement.text}</Field>
              {statement.evidence.map((item) => (
                <Field key={`${item.kind}-${item.ref}`} label={`Основание: ${item.kind}`}>
                  <OriginBadge origin={item.kind === "scenario" ? "scenario" : "derived"} />
                  <code>{item.ref}</code> = {num(item.value, 3)} — {item.detail}
                </Field>
              ))}
            </Fields>
          ) : null}

          <Note>
            Точки этой траектории — расчёт модели цепочки под выбранный план, а не измерения. Измеренные
            значения серы показаны отдельно на этапе «Доверие к данным», с возрастом каждого замера.
          </Note>
        </>
      )}

      <JsonPanel
        title="JSON: прогноз и траектория серы"
        value={{
          forecast: payload.forecast,
          forecast_used: payload.forecast_used,
          sulfur_checks: points,
          statements
        }}
      />
    </Section>
  );
}
