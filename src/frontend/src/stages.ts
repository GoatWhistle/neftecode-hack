import type { GateCheck, OptimizerRound, ScreenPayload, TrustReport } from "./types";
import { isNumber } from "./format";
import type { Lamp } from "./ui/Primitives";

export interface StageLamp {
  lamp: Lamp;
  title: string;
}

export interface Stage {
  id: string;
  label: string;
}

const SULFUR = "quality.sulfur_mgkg";

function trustLamp(payload: ScreenPayload): StageLamp {
  const event = (payload.decision.trace ?? []).find((item) => item.agent === "data");
  const report = event?.["report"];
  const trust = report && typeof report === "object" ? (report as TrustReport) : null;
  const sources = trust?.sources ? Object.values(trust.sources) : payload.sources ?? [];
  const usable = trust ? trust.usable : sources.some((item) => item.usable);
  if (sources.length === 0) return { lamp: "unknown", title: "источники не передавались" };
  return usable
    ? { lamp: "pass", title: "источник качества найден" }
    : { lamp: "fail", title: "достоверного источника нет" };
}

function gateLamp(payload: ScreenPayload): StageLamp {
  const checks = payload.decision.gate?.checks ?? [];
  if (checks.length === 0) return { lamp: "unknown", title: "проверки не передавались" };
  const title = payload.decision.gate?.feasible ? "план проходит" : "план не проходит";
  if (checks.some((check) => check.status === "fail")) return { lamp: "fail", title };
  if (checks.some((check) => check.status === "unknown")) return { lamp: "unknown", title };
  return { lamp: "pass", title };
}

function candidatesLamp(payload: ScreenPayload): StageLamp {
  const event = (payload.decision.trace ?? []).find((item) => item.agent === "optimizer");
  const rounds = (event?.["rounds"] as OptimizerRound[] | undefined) ?? [];
  if (rounds.length === 0) return { lamp: "unknown", title: "раунды поиска не передавались" };
  const feasible = rounds.reduce((acc, round) => acc + (round.feasible ?? 0), 0);
  return feasible > 0
    ? { lamp: "pass", title: "допустимые планы есть" }
    : { lamp: "fail", title: "допустимых планов не нашлось" };
}

function agentsLamp(payload: ScreenPayload): StageLamp {
  if (payload.agentic_state) return { lamp: "unknown", title: "агенты выключены" };
  const trace = payload.decision.trace ?? [];
  if (trace.length === 0) return { lamp: "unknown", title: "трасса участников пуста" };
  const vetoed = trace.some((event) => ((event["vetoes"] as unknown[] | undefined)?.length ?? 0) > 0);
  return { lamp: vetoed ? "fail" : "pass", title: `участников: ${trace.length}` };
}

function sulfurPoints(payload: ScreenPayload): GateCheck[] {
  return (payload.decision.gate?.checks ?? []).filter(
    (check) => check.constraint_id === SULFUR && isNumber(check.observed) && isNumber(check.time_hours)
  );
}

function forecastLamp(payload: ScreenPayload): StageLamp {
  const points = sulfurPoints(payload);
  if (points.length === 0) return { lamp: "unknown", title: "траектория не передавалась" };
  return points.some((check) => check.status !== "pass")
    ? { lamp: "fail", title: "сера против предела" }
    : { lamp: "pass", title: "сера против предела" };
}

function decisionLamp(payload: ScreenPayload): StageLamp {
  const title = payload.status_label;
  if (payload.decision.status === "refuse") return { lamp: "fail", title };
  return (payload.explanation.warnings?.length ?? 0) > 0
    ? { lamp: "unknown", title }
    : { lamp: "pass", title };
}

function stateLamp(payload: ScreenPayload): StageLamp {
  return payload.explanation.current_operation
    ? { lamp: "pass", title: "режим передан" }
    : { lamp: "unknown", title: "режим не передавался" };
}

function choiceLamp(payload: ScreenPayload): StageLamp {
  const plan = payload.decision.selected_plan;
  return plan
    ? { lamp: "pass", title: `выбран ${plan.plan_id}` }
    : { lamp: "fail", title: "план не выбран" };
}

const LAMPS: Record<string, (payload: ScreenPayload) => StageLamp> = {
  state: stateLamp,
  trust: trustLamp,
  forecast: forecastLamp,
  candidates: candidatesLamp,
  gate: gateLamp,
  agents: agentsLamp,
  choice: choiceLamp,
  decision: decisionLamp
};

export function lampOf(id: string, payload: ScreenPayload): StageLamp {
  const fn = LAMPS[id];
  return fn ? fn(payload) : { lamp: "unknown", title: "этап неизвестен" };
}

export const STAGES: readonly Stage[] = [
  { id: "state", label: "Состояние" },
  { id: "trust", label: "Доверие к данным" },
  { id: "candidates", label: "Кандидаты" },
  { id: "forecast", label: "Прогноз" },
  { id: "choice", label: "Выбор" },
  { id: "gate", label: "Gate" },
  { id: "agents", label: "Агенты" },
  { id: "decision", label: "Решение" }
];
