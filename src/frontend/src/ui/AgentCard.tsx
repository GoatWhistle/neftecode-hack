import type { SeverityFactors, TraceEvent } from "../types";
import { isNumber, num, termLabel } from "../format";
import type { Lamp } from "./Primitives";
import { LampDot, Note, Tag } from "./Primitives";
import { JsonPanel } from "./Json";

const TITLES: Record<string, string> = {
  data: "Агент данных",
  optimizer: "Оптимизатор",
  lookahead: "Проекция за горизонт",
  quality: "Агент качества",
  reliability: "Агент надёжности",
  robustness: "Проверка устойчивости"
};

const ROLES: Record<string, string> = {
  data: "решает, какому источнику верить",
  optimizer: "строит и отсеивает планы",
  lookahead: "смотрит за горизонт плана",
  quality: "вето по свойствам продукта",
  reliability: "вето по режиму и оборудованию",
  robustness: "держится ли план при возмущениях"
};

function lampOf(event: TraceEvent): Lamp {
  const verdict = event["verdict"];
  if (verdict === "pass") return "pass";
  if (verdict === "fail") return "fail";
  if (verdict === "unknown") return "unknown";
  if (event["usable"] === true) return "pass";
  if (event["usable"] === false) return "fail";
  if (event["fragile"] === true) return "unknown";
  if (event.agent === "optimizer" || event.agent === "lookahead") return "idle";
  return "idle";
}

function verdictText(event: TraceEvent): string {
  const verdict = event["verdict"];
  if (verdict === "pass") return "вето нет";
  if (verdict === "fail") return "наложено вето";
  if (verdict === "unknown") return "часть проверок неизвестна";
  if (event.agent === "data") return event["usable"] ? `основной источник: ${event["primary"]}` : "достоверного источника нет";
  if (event.agent === "robustness") return event["fragile"] ? "план чувствителен к возмущениям" : "план держится";
  if (event.agent === "optimizer") return `рассмотрено планов: ${num(event["evaluated"], 0)}`;
  if (event.agent === "lookahead") return event["available"] ? "проекция построена" : "проекция недоступна";
  return "—";
}

function counters(event: TraceEvent): Array<[string, string]> {
  const out: Array<[string, string]> = [];
  if (isNumber(event["checked"])) out.push(["проверено", num(event["checked"], 0)]);
  if (isNumber(event["passed"])) out.push(["пройдено", num(event["passed"], 0)]);
  const vetoes = event["vetoes"] as unknown[] | undefined;
  if (vetoes) out.push(["вето", String(vetoes.length)]);
  const unknown = event["unknown"] as unknown[] | undefined;
  if (unknown) out.push(["неизвестно", String(unknown.length)]);
  if (isNumber(event["held"])) out.push(["выдержал", num(event["held"], 0)]);
  if (isNumber(event["evaluated"])) out.push(["оценено", num(event["evaluated"], 0)]);
  if (isNumber(event["not_applicable"])) out.push(["неприменимо", num(event["not_applicable"], 0)]);
  if (isNumber(event["severity_index"])) out.push(["тяжесть режима", num(event["severity_index"], 3)]);
  return out;
}

function Severity({ factors }: { factors: SeverityFactors }) {
  return (
    <div className="severity">
      <table className="grid grid--tight">
        <caption>Из чего собран индекс тяжести режима: {num(factors.index, 3)}</caption>
        <thead>
          <tr>
            <th scope="col">Слагаемое</th>
            <th scope="col">Значение</th>
            <th scope="col">Вес</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(factors.terms ?? {}).map(([key, value]) => (
            <tr key={key}>
              <th scope="row">{termLabel(key)}</th>
              <td className="grid__num">{num(value, 3)}</td>
              <td className="grid__num">{num(factors.weights?.[key], 2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="severity__refs">
        Опорная температура <b>{num(factors.reference_temp_c, 1)} °C</b>, опорный расход{" "}
        <b>{num(factors.reference_flow_m3h, 1)} м³/ч</b>
        {factors.control_range_c ? (
          <>
            , диапазон уставки{" "}
            <b>
              {num(factors.control_range_c[0], 0)}–{num(factors.control_range_c[1], 0)} °C
            </b>
          </>
        ) : null}
        .
      </p>
      {factors.scope ? <Note>{factors.scope}</Note> : null}
    </div>
  );
}

export function AgentCard({ event }: { event: TraceEvent }) {
  const severity = event["severity_factors"] as SeverityFactors | undefined;
  const vetoes = (event["vetoes"] as string[] | undefined) ?? [];
  const unknown = (event["unknown"] as string[] | undefined) ?? [];
  const scope = event["scope"] as string | undefined;

  return (
    <article className="agent">
      <header className="agent__head">
        <h3 className="agent__name">
          <LampDot state={lampOf(event)} />
          {TITLES[event.agent] ?? event.agent}
        </h3>
        <p className="agent__role">{ROLES[event.agent] ?? "участник трассы"}</p>
        <Tag tone={lampOf(event)}>{verdictText(event)}</Tag>
      </header>

      {counters(event).length > 0 ? (
        <dl className="agent__counters">
          {counters(event).map(([label, value]) => (
            <div key={label} className="agent__counter">
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      ) : null}

      {vetoes.length > 0 ? (
        <ul className="agent__list agent__list--veto">
          {vetoes.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      ) : null}

      {unknown.length > 0 ? (
        <ul className="agent__list agent__list--unknown">
          {unknown.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      ) : null}

      {severity ? <Severity factors={severity} /> : null}
      {scope ? <Note>{scope}</Note> : null}

      <JsonPanel title={`JSON агента «${event.agent}»`} value={event} openTo={2} />
    </article>
  );
}
