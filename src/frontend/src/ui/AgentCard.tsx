import type { SeverityFactors, TraceEvent } from "../types";
import { isNumber, num } from "../format";
import type { Lamp } from "./Primitives";
import { LampDot, Tag } from "./Primitives";
import { JsonPanel } from "./Json";

const TITLES: Record<string, string> = {
  data: "Агент данных",
  optimizer: "Оптимизатор",
  lookahead: "Проекция за горизонт",
  quality: "Агент качества",
  reliability: "Агент надёжности",
  robustness: "Проверка устойчивости",
  agentic: "Агентный слой",
  tank_estimate: "Оценка резервуара"
};

const ROLES: Record<string, string> = {
  data: "решает, какому источнику верить",
  optimizer: "строит и отсеивает планы",
  lookahead: "смотрит за горизонт плана",
  quality: "вето по свойствам продукта",
  reliability: "вето по режиму и оборудованию",
  robustness: "держится ли план при возмущениях",
  agentic: "сводит мнения в итоговый выбор",
  tank_estimate: "оценка состава резервуара"
};

function lampOf(event: TraceEvent): Lamp {
  const verdict = event["verdict"];
  if (verdict === "pass") return "pass";
  if (verdict === "fail") return "fail";
  if (verdict === "unknown") return "unknown";
  if (event["usable"] === true) return "pass";
  if (event["usable"] === false) return "fail";
  if (event["fragile"] === true) return "unknown";
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
  if (event.agent === "agentic") {
    const action = event["action"];
    if (action === "select") return `выбран план ${event["selected"] ?? "не назван"}`;
    if (action === "refuse") return "агенты дошли до отказа";
    return typeof action === "string" ? action : "итог не передан";
  }
  if (event.agent === "tank_estimate") {
    if (event["available"] !== true) return "оценка не строилась";
    return event["sensitive"] === true ? "решение чувствительно к оценке" : "решение устойчиво к оценке";
  }
  return "—";
}

interface SourceRow {
  name: string;
  usable: boolean;
  age: number | null;
  maxAge: number | null;
}

function sourceRows(event: TraceEvent): SourceRow[] {
  const report = event["report"] as { sources?: Record<string, Record<string, unknown>> } | undefined;
  const sources = report?.sources;
  if (!sources) return [];
  return Object.entries(sources).map(([key, raw]) => ({
    name: typeof raw["name"] === "string" ? (raw["name"] as string) : key,
    usable: raw["usable"] === true,
    age: isNumber(raw["age_hours"]) ? (raw["age_hours"] as number) : null,
    maxAge: isNumber(raw["max_age_hours"]) ? (raw["max_age_hours"] as number) : null
  }));
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
  if (isNumber(event["allowed"])) out.push(["допущено", num(event["allowed"], 0)]);
  if (isNumber(event["changed"])) out.push(["меняет решение", num(event["changed"], 0)]);
  const applied = event["constraints"] as unknown[] | undefined;
  if (applied) out.push(["ограничений", String(applied.length)]);
  const vetoedPlans = event["vetoed"] as unknown[] | undefined;
  if (vetoedPlans) out.push(["планов под вето", String(vetoedPlans.length)]);
  if (isNumber(event["lookahead_hours"])) out.push(["горизонт, ч", num(event["lookahead_hours"], 0)]);
  if (isNumber(event["min_reaction_hours"])) out.push(["запас реакции, ч", num(event["min_reaction_hours"], 0)]);
  if (isNumber(event["examined"])) out.push(["планов проверено", num(event["examined"], 0)]);
  if (event.agent === "lookahead" && typeof event["switched"] === "boolean") {
    out.push(["план сменён", event["switched"] ? "да" : "нет"]);
  }
  const sources = (event["report"] as { sources?: Record<string, unknown> } | undefined)?.sources;
  if (sources) out.push(["источников сверено", String(Object.keys(sources).length)]);
  return out;
}

export function AgentCard({ event }: { event: TraceEvent }) {
  const severity = event["severity_factors"] as SeverityFactors | undefined;
  const vetoes = (event["vetoes"] as string[] | undefined) ?? [];
  const unknown = (event["unknown"] as string[] | undefined) ?? [];
  const scope = event["scope"] as string | undefined;
  const rows = counters(event);
  const sources = sourceRows(event);
  const primary = event["primary"];
  const lamp = lampOf(event);

  return (
    <article className="agent">
      <header className="agent__head">
        <h4 className="agent__name">
          <LampDot state={lamp} />
          {TITLES[event.agent] ?? event.agent}
        </h4>
        <p className="agent__role">{ROLES[event.agent] ?? "участник трассы"}</p>
        <Tag tone={lamp}>{verdictText(event)}</Tag>
      </header>

      <div className="agent__body">
        {rows.length > 0 ? (
          <dl className="agent__counters">
            {rows.map(([label, value]) => (
              <div key={label} className="agent__counter">
                <dt>{label}</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>
        ) : null}

        {sources.length > 0 ? (
          <ul className="agent__sources">
            {sources.map((row) => (
              <li key={row.name} className={`agent__source${row.usable ? "" : " agent__source--off"}`}>
                <span className="agent__source-name">
                  {row.name}
                  {row.name === primary ? <i className="agent__source-flag">основной</i> : null}
                </span>
                <span className="agent__source-age">
                  {row.age === null ? "возраст не передан" : `${num(row.age, 1)} ч`}
                  {row.maxAge === null ? "" : ` из ${num(row.maxAge, 1)}`}
                </span>
              </li>
            ))}
          </ul>
        ) : null}

        {vetoes.length > 0 ? (
          <ul className="agent__list agent__list--veto">
            {vetoes.map((reason, index) => (
              <li key={`${index}-${reason}`}>{reason}</li>
            ))}
          </ul>
        ) : null}

        {unknown.length > 0 ? (
          <ul className="agent__list agent__list--unknown">
            {unknown.map((reason, index) => (
              <li key={`${index}-${reason}`}>{reason}</li>
            ))}
          </ul>
        ) : null}

        {severity ? (
          <p className="agent__pointer">
            Разложение тяжести режима вынесено под сетку: там ему хватает ширины строки.
          </p>
        ) : null}

        {scope ? <p className="agent__scope">{scope}</p> : null}
      </div>

      <div className="agent__foot">
        <JsonPanel title={`JSON агента «${event.agent}»`} value={event} openTo={2} />
      </div>
    </article>
  );
}
