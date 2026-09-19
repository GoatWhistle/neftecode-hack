import type { TraceEvent } from "../types";
import { isNumber, num } from "../format";
import type { Lamp } from "./Primitives";
import { LampDot, Tag } from "./Primitives";

const NAMES: Record<string, string> = {
  data: "агент данных",
  optimizer: "оптимизатор",
  lookahead: "проекция за горизонт",
  quality: "агент качества",
  reliability: "агент надёжности",
  robustness: "проверка устойчивости"
};

const TOOLS: Record<string, string> = {
  data: "правила доверия к источникам",
  optimizer: "перебор планов в бюджете",
  lookahead: "модель смешения за горизонтом плана",
  quality: "предельные значения продукта",
  reliability: "границы режима и оборудования",
  robustness: "прогон плана под возмущениями"
};

function lampOf(event: TraceEvent): Lamp {
  const verdict = event["verdict"];
  if (verdict === "pass" || event["usable"] === true) return "pass";
  if (verdict === "fail" || event["usable"] === false) return "fail";
  if (verdict === "unknown" || event["fragile"] === true) return "unknown";
  return "idle";
}

function returned(event: TraceEvent): string {
  const parts: string[] = [];
  if (isNumber(event["evaluated"])) parts.push(`оценено планов ${num(event["evaluated"], 0)}`);
  if (isNumber(event["checked"])) parts.push(`проверок ${num(event["checked"], 0)}`);
  if (isNumber(event["passed"])) parts.push(`пройдено ${num(event["passed"], 0)}`);
  if (isNumber(event["held"])) parts.push(`выдержало ${num(event["held"], 0)}`);
  const vetoes = (event["vetoes"] as unknown[] | undefined) ?? [];
  if (vetoes.length > 0) parts.push(`вето ${vetoes.length}`);
  const unknown = (event["unknown"] as unknown[] | undefined) ?? [];
  if (unknown.length > 0) parts.push(`неизвестно ${unknown.length}`);
  if (typeof event["primary"] === "string") parts.push(`основной источник ${event["primary"]}`);
  return parts.length > 0 ? parts.join(", ") : "сводных счётчиков не передано";
}

function verdict(event: TraceEvent): string {
  const value = event["verdict"];
  if (value === "pass") return "вето нет";
  if (value === "fail") return "наложено вето";
  if (value === "unknown") return "часть проверок неизвестна";
  if (event["usable"] === true) return "источнику можно верить";
  if (event["usable"] === false) return "достоверного источника нет";
  if (event["fragile"] === true) return "план чувствителен к возмущениям";
  if (event["fragile"] === false) return "план держится";
  return "вердикт не передавался";
}

export interface TraceLineProps {
  event: TraceEvent;
  position: number;
}

export function TraceLine({ event, position }: TraceLineProps) {
  const lamp = lampOf(event);
  const name = NAMES[event.agent] ?? event.agent;

  return (
    <li className="trace__item">
      <span className="trace__order">{position}</span>
      <div className="trace__body">
        <p className="trace__ask">
          <b>оркестратор</b> спрашивает <b>{name}</b>
        </p>
        <p className="trace__tool">инструмент: {TOOLS[event.agent] ?? "не описан в трассе"}</p>
        <p className="trace__result">вернул: {returned(event)}</p>
        <p className="trace__verdict">
          <LampDot state={lamp} />
          <Tag tone={lamp}>{verdict(event)}</Tag>
        </p>
      </div>
    </li>
  );
}
