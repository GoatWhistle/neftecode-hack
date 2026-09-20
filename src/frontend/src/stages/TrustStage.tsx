import type { SourceVerdict, TraceEvent, TrustReport } from "../types";
import { hours, num, percent } from "../format";
import { Empty, Field, Fields, LampDot, Note, Readout, Scroller, Tag } from "../ui/Primitives";
import { OriginBadge } from "../ui/Origin";
import { Section } from "../ui/Section";
import { JsonPanel } from "../ui/Json";
import { AgeBars } from "../ui/AgeBars";
import type { StageProps } from "./StateStage";

function reportOf(trace: TraceEvent[]): TrustReport | null {
  const event = trace.find((item) => item.agent === "data");
  const report = event?.["report"];
  return report && typeof report === "object" ? (report as TrustReport) : null;
}

function verdicts(report: TrustReport | null, fallback: SourceVerdict[]): SourceVerdict[] {
  if (report && report.sources) return Object.values(report.sources);
  return fallback ?? [];
}

export function TrustStage({ payload, index, state, source, lamp, lampTitle, bare }: StageProps) {
  const report = reportOf(payload.decision.trace ?? []);
  const sources = verdicts(report, payload.sources);
  const missing = report?.telemetry_missing_fraction ?? null;
  const suspects = report?.suspect_values ?? [];

  return (
    <Section
      id="trust"
      index={index}
      state={state}
      source={source}
      title="Доверие к данным"
      lead="Агент данных решает, какому источнику можно верить: возраст замера, пригодность, пропуски телеметрии."
      lamp={lamp}
      lampTitle={lampTitle}
      bare={bare}
    >
      {sources.length === 0 ? (
        <Empty>
          Состояние источников не передавалось: в этом пути расчёта блок «доверие к данным» пуст.
          Пустое поле здесь означает отсутствие данных, а не их благополучие.
        </Empty>
      ) : (
        <>
          <AgeBars sources={sources} />

          <Scroller label="Источники качества">
            <table className="grid">
              <caption>Источники качества</caption>
              <thead>
                <tr>
                  <th scope="col">Источник</th>
                  <th scope="col">Значение серы</th>
                  <th scope="col">Возраст</th>
                  <th scope="col">Предел возраста</th>
                  <th scope="col">Пригоден</th>
                </tr>
              </thead>
              <tbody>
                {sources.map((source) => (
                  <tr key={source.name}>
                    <th scope="row">
                      {source.name}
                      {report?.primary === source.name ? <Tag tone="pass">основной</Tag> : null}
                    </th>
                    <td className="grid__num">
                      <OriginBadge origin="measured" />
                      {num(source.value, 2)} мг/кг
                    </td>
                    <td className="grid__num">{hours(source.age_hours)}</td>
                    <td className="grid__num">{hours(source.max_age_hours)}</td>
                    <td>
                      <LampDot state={source.usable ? "pass" : "fail"} />
                      {source.status}
                      {source.reasons.length > 0 ? (
                        <span className="grid__reasons">{source.reasons.join("; ")}</span>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Scroller>

          <div className="readouts">
            <Readout
              label="Пропуски телеметрии"
              value={missing === null ? "—" : percent(missing)}
              tone={missing !== null && missing > 0 ? "unknown" : "pass"}
              hint={missing === null ? "доля не передавалась" : "доля отсутствующих тегов"}
            />
            <Readout
              label="Подозрительные значения"
              value={String(suspects.length)}
              tone={suspects.length > 0 ? "unknown" : "pass"}
              hint="помечены, но источник не отозван"
            />
            <Readout
              label="Режим подмены источника"
              value={report?.fallback ? "включён" : "выключен"}
              tone={report?.fallback ? "unknown" : "pass"}
            />
          </div>

          {suspects.length > 0 ? (
            <Scroller label="Значения, помеченные к проверке">
              <table className="grid">
                <caption>Значения, помеченные к проверке</caption>
                <thead>
                  <tr>
                    <th scope="col">Тег</th>
                    <th scope="col">Значение</th>
                    <th scope="col">Почему помечено</th>
                  </tr>
                </thead>
                <tbody>
                  {suspects.map((item) => (
                    <tr key={`${item.tag}-${item.value}`}>
                      <th scope="row">
                        <code>{item.tag}</code>
                      </th>
                      <td className="grid__num">{num(item.value, 3)}</td>
                      <td>{item.note}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Scroller>
          ) : null}

          <Fields>
            <Field label="Замер на момент">{report?.as_of ?? "—"}</Field>
            <Field label="Недостающие требования">
              {report?.missing_requirements?.length ? report.missing_requirements.join("; ") : "нет"}
            </Field>
            <Field label="Причина отказа от данных">{report?.refusal_reason ?? "нет"}</Field>
          </Fields>

          {report?.rule ? <Note>{report.rule}</Note> : null}

          <Note>
            Значения в этой таблице — единственные на странице, снятые с источников измерения. Всё остальное
            либо требование ТЗ, либо наш расчёт, либо допущение сценария; каждое помечено своим бейджем.
            {payload.state_origin ? ` Происхождение состояния: ${payload.state_origin}.` : ""}
          </Note>
        </>
      )}

      <JsonPanel
        title="JSON: отчёт агента данных"
        value={report ?? { sources: payload.sources, note: "полный отчёт агента данных не передавался" }}
        openTo={2}
      />
    </Section>
  );
}
